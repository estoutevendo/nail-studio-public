import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

import schemas
from auth import (
    criar_token,
    exigir_acesso,
    gerar_hash,
    verificar_senha,
    verificar_token,
)
from database import Base, SessionLocal, engine
from email_service import (
    email_atendimento_solicitado,
    email_cancelamento,
    email_confirmacao,
    email_novo_agendamento,
)
from models import Agendamento, Cliente, Servico, Sessao
from scheduler import scheduler
from tempo import agora_br

STATUS_ATIVOS = ["agendado", "confirmado"]

HORARIOS_SEMANA = ["07:00", "08:30", "10:00", "13:00", "14:30", "16:00"]
HORARIOS_SABADO = ["07:00", "08:30", "10:00", "11:30"]

# Dias sem atendimento, no formato DD/MM (é o que o strftime("%d/%m") devolve).
# Sexta-feira Santa e Corpus Christi mudam todo ano, então precisam ser
# atualizados na virada.
FERIADOS = [
    "03/04", "21/04", "01/05", "15/05", "16/05", "04/06", "02/07", "07/09",
    "12/10", "02/11", "15/11", "25/12", "22/06", "13/07",
]

# Cancelar com menos de 10h de antecedência gera cobrança de 50% no próximo
# agendamento. Agendar com menos de 4h não é permitido.
HORAS_TAXA_CANCELAMENTO = 10
HORAS_MIN_ANTECEDENCIA = 4
# Quem marca para as próximas 24h já entra como confirmado (não dá tempo de
# mandar o lembrete do dia anterior)
HORAS_CONFIRMACAO_AUTOMATICA = 24


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Nail Studio API", lifespan=lifespan)

# A autenticação é por header (Bearer / X-API-Key) e não por cookie, então não
# precisa de allow_credentials. Em produção, troque "*" pelo domínio do painel.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tudo que está nesse router exige login do painel ou a chave do bot.
# Só /login e /verificar-token ficam abertos.
protegido = APIRouter(dependencies=[Depends(exigir_acesso)])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def horarios_do_dia(dia: datetime) -> list[str]:
    return HORARIOS_SABADO if dia.weekday() == 5 else HORARIOS_SEMANA


def validar_dia_de_atendimento(dia: datetime):
    if dia.weekday() == 6:
        raise HTTPException(status_code=400, detail="Não atendemos aos domingos.")
    if dia.strftime("%d/%m") in FERIADOS:
        raise HTTPException(status_code=400, detail="Não atendemos em feriados.")


def horario_ocupado(db: Session, data_hora: datetime, ignorar_id: int | None = None) -> bool:
    consulta = db.query(Agendamento).filter(
        Agendamento.status.in_(STATUS_ATIVOS),
        Agendamento.data_hora == data_hora,
    )
    if ignorar_id is not None:
        consulta = consulta.filter(Agendamento.id != ignorar_id)
    return consulta.first() is not None


# ---------- serviços e clientes ----------

@protegido.get("/servicos", response_model=list[schemas.ServicoOut])
def listar_servicos(db: Session = Depends(get_db)):
    return db.query(Servico).all()


@protegido.post("/clientes", response_model=schemas.ClienteOut)
def cadastrar_cliente(cliente: schemas.ClienteCreate, db: Session = Depends(get_db)):
    # o telefone é a identidade da cliente: se já existe, devolve a mesma
    existente = db.query(Cliente).filter(Cliente.telefone == cliente.telefone).first()
    if existente:
        return existente

    novo = Cliente(nome=cliente.nome, telefone=cliente.telefone)
    db.add(novo)
    db.commit()
    db.refresh(novo)
    return novo


@protegido.get("/clientes/{telefone}", response_model=schemas.ClienteOut)
def buscar_cliente(telefone: str, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.telefone == telefone).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrada.")
    return cliente


# ---------- agendamentos ----------

@protegido.post("/agendamentos", response_model=schemas.AgendamentoOut)
def criar_agendamento(dados: schemas.AgendamentoCreate, db: Session = Depends(get_db)):
    # o banco guarda horário local sem fuso, então descartamos o tzinfo que
    # possa vir no JSON
    data_hora = dados.data_hora.replace(tzinfo=None)
    agora = agora_br()

    cliente = db.query(Cliente).filter(Cliente.telefone == dados.telefone).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrada. Cadastre-se primeiro.")

    # uma cliente só pode ter um agendamento futuro por vez
    ja_marcado = db.query(Agendamento).filter(
        Agendamento.cliente_id == cliente.id,
        Agendamento.status.in_(STATUS_ATIVOS),
        Agendamento.data_hora >= agora,
    ).first()
    if ja_marcado:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Você já tem um agendamento marcado para "
                f"{ja_marcado.data_hora.strftime('%d/%m/%Y às %H:%M')}. "
                f"Cancele-o antes de fazer um novo."
            ),
        )

    servico = db.query(Servico).filter(Servico.id == dados.servico_id).first()
    if not servico:
        raise HTTPException(status_code=404, detail="Serviço não encontrado.")

    validar_dia_de_atendimento(data_hora)

    horarios = horarios_do_dia(data_hora)
    if data_hora.strftime("%H:%M") not in horarios:
        prefixo = "Horários disponíveis aos sábados" if data_hora.weekday() == 5 else "Horários disponíveis"
        raise HTTPException(status_code=400, detail=f"{prefixo}: {', '.join(horarios)}")

    horas_ate_o_horario = (data_hora - agora).total_seconds() / 3600
    if horas_ate_o_horario < HORAS_MIN_ANTECEDENCIA:
        raise HTTPException(
            status_code=400,
            detail=f"Agendamentos devem ser feitos com no mínimo {HORAS_MIN_ANTECEDENCIA}h de antecedência.",
        )

    if horario_ocupado(db, data_hora):
        raise HTTPException(status_code=400, detail="Horário indisponível. Escolha outro horário.")

    status_inicial = "confirmado" if horas_ate_o_horario <= HORAS_CONFIRMACAO_AUTOMATICA else "agendado"

    novo = Agendamento(
        cliente_id=cliente.id,
        servico_id=servico.id,
        data_hora=data_hora,
        status=status_inicial,
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)

    email_novo_agendamento(
        nome=cliente.nome,
        telefone=cliente.telefone,
        servico=servico.nome,
        data_hora=novo.data_hora.strftime("%d/%m/%Y às %H:%M"),
        valor=float(servico.preco),
    )

    return novo


@protegido.get("/agendamentos/{telefone}", response_model=list[schemas.AgendamentoOut])
def ver_agendamentos(telefone: str, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.telefone == telefone).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrada.")

    return db.query(Agendamento).filter(
        Agendamento.cliente_id == cliente.id,
        Agendamento.status.in_(STATUS_ATIVOS),
        Agendamento.data_hora >= agora_br(),
    ).all()


@protegido.patch("/agendamentos/{id}/cancelar")
def cancelar_agendamento(id: int, telefone: str, db: Session = Depends(get_db)):
    agendamento = db.query(Agendamento).filter(Agendamento.id == id).first()
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")

    # só a dona do agendamento pode cancelar por aqui
    cliente = db.query(Cliente).filter(Cliente.telefone == telefone).first()
    if not cliente or agendamento.cliente_id != cliente.id:
        raise HTTPException(status_code=403, detail="Você não tem permissão para cancelar este agendamento.")

    if agendamento.status not in STATUS_ATIVOS:
        raise HTTPException(status_code=400, detail="Este agendamento não pode mais ser cancelado.")

    horas_restantes = (agendamento.data_hora - agora_br()).total_seconds() / 3600
    taxa = horas_restantes < HORAS_TAXA_CANCELAMENTO

    agendamento.status = "cancelado"
    db.commit()

    email_cancelamento(
        nome=agendamento.cliente.nome,
        telefone=agendamento.cliente.telefone,
        servico=agendamento.servico.nome,
        data_hora=agendamento.data_hora.strftime("%d/%m/%Y às %H:%M"),
        taxa=taxa,
    )

    if taxa:
        return {
            "mensagem": f"Cancelamento com menos de {HORAS_TAXA_CANCELAMENTO}h. Será cobrado 50% no próximo agendamento.",
            "taxa": True,
        }
    return {"mensagem": "Agendamento cancelado com sucesso.", "taxa": False}


@protegido.patch("/agendamentos/{id}/confirmar")
def confirmar_agendamento(id: int, db: Session = Depends(get_db)):
    ag = db.query(Agendamento).filter(Agendamento.id == id).first()
    if not ag:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")

    ag.status = "confirmado"
    db.commit()

    email_confirmacao(
        nome=ag.cliente.nome,
        telefone=ag.cliente.telefone,
        servico=ag.servico.nome,
        data_hora=ag.data_hora.strftime("%d/%m/%Y às %H:%M"),
    )
    return {"ok": True}


@protegido.get("/horarios-disponiveis")
def horarios_disponiveis(data: str, db: Session = Depends(get_db)):
    # `data` vem como DD/MM/AAAA
    try:
        dia = datetime.strptime(data, "%d/%m/%Y")
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use DD/MM/AAAA")

    validar_dia_de_atendimento(dia)

    # uma consulta só para o dia inteiro, em vez de uma por horário
    ocupados = {
        ag.data_hora.strftime("%H:%M")
        for ag in db.query(Agendamento).filter(
            Agendamento.status.in_(STATUS_ATIVOS),
            Agendamento.data_hora >= dia,
            Agendamento.data_hora < dia + timedelta(days=1),
        )
    }

    # não oferece horário que a regra das 4h de antecedência já vai recusar
    limite = agora_br() + timedelta(hours=HORAS_MIN_ANTECEDENCIA)
    disponiveis = [
        h for h in horarios_do_dia(dia)
        if h not in ocupados and datetime.strptime(f"{data} {h}", "%d/%m/%Y %H:%M") >= limite
    ]

    return {"data": data, "horarios": disponiveis}


@protegido.post("/email-atendimento")
def notificar_atendimento(dados: dict, db: Session = Depends(get_db)):
    telefone = dados.get("telefone")
    cliente = db.query(Cliente).filter(Cliente.telefone == telefone).first()
    nome = cliente.nome if cliente else telefone
    email_atendimento_solicitado(nome=nome, telefone=telefone)
    return {"ok": True}


# ---------- área administrativa (painel e menu admin do bot) ----------

@protegido.get("/admin/agendamentos", response_model=list[schemas.AgendamentoOut])
def admin_agendamentos(data: str, db: Session = Depends(get_db)):
    try:
        dia = datetime.strptime(data, "%d/%m/%Y")
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use DD/MM/AAAA")

    return db.query(Agendamento).filter(
        Agendamento.status.in_(["agendado", "confirmado", "concluido"]),
        Agendamento.data_hora >= dia,
        Agendamento.data_hora < dia + timedelta(days=1),
    ).order_by(Agendamento.data_hora).all()


@protegido.get("/admin/clientes", response_model=list[schemas.ClienteOut])
def admin_clientes(db: Session = Depends(get_db)):
    return db.query(Cliente).order_by(Cliente.nome).all()


@protegido.patch("/admin/agendamentos/{id}/cancelar")
def admin_cancelar(id: int, db: Session = Depends(get_db)):
    ag = db.query(Agendamento).filter(Agendamento.id == id).first()
    if not ag:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")
    ag.status = "cancelado"
    db.commit()
    return {"mensagem": "Agendamento cancelado com sucesso."}


@protegido.patch("/admin/agendamentos/{id}/editar")
def editar_agendamento(id: int, dados: schemas.EdicaoIn, db: Session = Depends(get_db)):
    ag = db.query(Agendamento).filter(Agendamento.id == id).first()
    if not ag:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")

    nova_data = dados.data_hora.replace(tzinfo=None)
    validar_dia_de_atendimento(nova_data)
    if nova_data.strftime("%H:%M") not in horarios_do_dia(nova_data):
        raise HTTPException(status_code=400, detail="Horário fora do expediente.")
    if horario_ocupado(db, nova_data, ignorar_id=ag.id):
        raise HTTPException(status_code=400, detail="Horário indisponível. Escolha outro horário.")

    ag.data_hora = nova_data
    db.commit()
    return {"mensagem": "Agendamento atualizado com sucesso."}


# ---------- sessões do bot ----------
# O bot guarda em que etapa da conversa cada cliente está. Fica no banco (e não
# em memória) para a conversa sobreviver a um restart do bot.

@protegido.get("/sessoes/{telefone}")
def carregar_sessao(telefone: str, db: Session = Depends(get_db)):
    sessao = db.query(Sessao).filter(Sessao.telefone == telefone).first()
    if not sessao:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    return json.loads(sessao.dados)


@protegido.post("/sessoes/{telefone}")
def salvar_sessao(telefone: str, dados: dict, db: Session = Depends(get_db)):
    sessao = db.query(Sessao).filter(Sessao.telefone == telefone).first()
    if sessao:
        sessao.dados = json.dumps(dados)
    else:
        db.add(Sessao(telefone=telefone, dados=json.dumps(dados)))
    db.commit()
    return {"ok": True}


app.include_router(protegido)


# ---------- login do painel ----------

SENHA_PAINEL = os.getenv("SENHA_PAINEL")
if not SENHA_PAINEL:
    raise RuntimeError("Defina SENHA_PAINEL no .env (veja o .env.example)")
SENHA_HASH = gerar_hash(SENHA_PAINEL)


@app.post("/login")
def login(dados: schemas.LoginIn):
    if not verificar_senha(dados.senha, SENHA_HASH):
        raise HTTPException(status_code=401, detail="Senha incorreta.")
    return {"token": criar_token({"sub": "admin"})}


@app.get("/verificar-token")
def verificar(token: str):
    if not verificar_token(token):
        raise HTTPException(status_code=401, detail="Token inválido ou expirado.")
    return {"ok": True}
