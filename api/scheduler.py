import os
from datetime import datetime, timedelta
from html import escape

import requests
from apscheduler.schedulers.background import BackgroundScheduler

from database import SessionLocal
from email_service import enviar_email
from models import Agendamento
from tempo import FUSO, agora_br

# Número do ateliê no formato 55 + DDD + número. É para ele que vai o resumo
# diário no WhatsApp.
NUMERO_ATELIE = os.getenv("NUMERO_ATELIE", "")

# O bot (Node) escuta aqui e é quem de fato manda as mensagens no WhatsApp
BOT_URL = os.getenv("BOT_URL", "http://127.0.0.1:3001")


def verificar_lembretes():
    db = SessionLocal()
    try:
        amanha_inicio = agora_br() + timedelta(days=1)
        amanha_inicio = amanha_inicio.replace(hour=0, minute=0, second=0, microsecond=0)
        amanha_fim    = amanha_inicio + timedelta(hours=24)

        agendamentos = db.query(Agendamento).filter(
            Agendamento.status    == "agendado",
            Agendamento.data_hora >= amanha_inicio,
            Agendamento.data_hora <  amanha_fim
        ).all()

        for ag in agendamentos:
            telefone = ag.cliente.telefone
            nome     = ag.cliente.nome
            servico  = ag.servico.nome
            horario  = ag.data_hora.strftime("%d/%m/%Y às %H:%M")

            mensagem = (
                f"Olá {nome}! 💅\n"
                f"Lembrando que você tem um agendamento amanhã:\n"
                f"✂️ Serviço: {servico}\n"
                f"🕐 Horário: {horario}\n\n"
                f"Por favor, confirme sua presença:\n"
                f"✅ Digite *sim* para confirmar\n"
                f"❌ Digite *não* para cancelar\n\n"
                f"📍 Em caso de cancelamento, avise com pelo menos 10h de antecedência."
            )

            try:
                requests.post(BOT_URL, json={
                    "telefone": telefone,
                    "mensagem": mensagem,
                    "agendamento_id": ag.id
                }, timeout=10)
                print(f"[LEMBRETE] Enviado para {telefone}")
            except Exception as e:
                print(f"[LEMBRETE] Erro ao enviar para {telefone}: {e}")


    finally:
        db.close()

def resumo_diario():
    db = SessionLocal()
    try:
        hoje_inicio = agora_br().replace(hour=0, minute=0, second=0, microsecond=0)
        hoje_fim    = hoje_inicio + timedelta(hours=24)

        # quem marcou para as últimas 24h já entra como "confirmado", então
        # filtrar só "agendado" deixava esses horários fora do resumo
        agendamentos = db.query(Agendamento).filter(
            Agendamento.status.in_(["agendado", "confirmado"]),
            Agendamento.data_hora >= hoje_inicio,
            Agendamento.data_hora <  hoje_fim
        ).order_by(Agendamento.data_hora).all()

        if not agendamentos:
            mensagem = "📭 Nenhum agendamento para hoje!"
        else:
            mensagem = f"📅 *Agendamentos de hoje — {hoje_inicio.strftime('%d/%m/%Y')}*\n\n"
            for ag in agendamentos:
                horario = ag.data_hora.strftime("%H:%M")
                mensagem += f"🕐 *{horario}* — {ag.cliente.nome}\n"
                mensagem += f"   ✂️ {ag.servico.nome}\n"
                mensagem += f"   📞 {ag.cliente.telefone}\n\n"

        if not NUMERO_ATELIE:
            print("[RESUMO] NUMERO_ATELIE não configurado, resumo não enviado.")
            return

        try:
            requests.post(BOT_URL, json={
                "telefone": NUMERO_ATELIE.removeprefix("55"),  # o bot adiciona o 55 de volta
                "mensagem": mensagem
            }, timeout=10)
        except Exception as e:
            print(f"[RESUMO] Erro ao enviar: {e}")

    finally:
        db.close()

def concluir_agendamentos_passados():
    db = SessionLocal()
    try:
        agora = agora_br()
        # considera concluído quem começou há mais de 3h20 (duração do maior serviço + folga)
        limite = agora - timedelta(hours=3, minutes=20)

        agendamentos = db.query(Agendamento).filter(
            Agendamento.status.in_(["agendado", "confirmado"]),
            Agendamento.data_hora <= limite
        ).all()

        for ag in agendamentos:
            ag.status = "concluido"

        db.commit()
        print(f"[SCHEDULER] {len(agendamentos)} agendamentos marcados como concluídos.")
    finally:
        db.close()

def resumo_dia_email():
    db = SessionLocal()
    try:
        agora = agora_br()
        inicio = agora.replace(hour=0, minute=0, second=0, microsecond=0)
        fim    = agora.replace(hour=23, minute=59, second=59)

        agendamentos = db.query(Agendamento).filter(
            Agendamento.data_hora >= inicio,
            Agendamento.data_hora <= fim
        ).all()

        total      = len(agendamentos)
        concluidos = sum(1 for a in agendamentos if a.status == "concluido")
        agendados  = sum(1 for a in agendamentos if a.status in ("agendado", "confirmado"))
        cancelados = sum(1 for a in agendamentos if a.status == "cancelado")
        faturamento = sum(float(a.servico.preco) for a in agendamentos if a.status in ("agendado", "confirmado", "concluido"))

        linhas = ""
        for a in sorted(agendamentos, key=lambda x: x.data_hora):
            horario = a.data_hora.strftime("%H:%M")
            linhas += f"<tr><td>{horario}</td><td>{escape(a.cliente.nome)}</td><td>{escape(a.servico.nome)}</td><td>R$ {a.servico.preco}</td><td>{a.status}</td></tr>"

        corpo = f"""
        <h2>📊 Resumo do dia — {agora.strftime('%d/%m/%Y')}</h2>
        <p>👥 Total: <b>{total}</b> | ✅ Concluídos: <b>{concluidos}</b> | 📅 Agendados: <b>{agendados}</b> | ❌ Cancelados: <b>{cancelados}</b></p>
        <p>💰 Faturamento do dia: <b>R$ {faturamento:.2f}</b></p>
        <br>
        <table border="1" cellpadding="6">
            <tr><th>Horário</th><th>Cliente</th><th>Serviço</th><th>Valor</th><th>Status</th></tr>
            {linhas}
        </table>
        """

        enviar_email(f"📊 Resumo do dia — {agora.strftime('%d/%m/%Y')}", corpo)
        print("[SCHEDULER] Resumo do dia enviado por e-mail.")
    finally:
        db.close()

def resumo_mes_email():
    db = SessionLocal()
    try:
        agora  = agora_br()
        mes    = agora.month
        ano    = agora.year
        inicio = datetime(ano, mes, 1)
        fim    = datetime(ano, mes + 1, 1) if mes < 12 else datetime(ano + 1, 1, 1)

        agendamentos = db.query(Agendamento).filter(
            Agendamento.data_hora >= inicio,
            Agendamento.data_hora <  fim
        ).all()

        total                = len(agendamentos)
        concluidos           = sum(1 for a in agendamentos if a.status == "concluido")
        agendados            = sum(1 for a in agendamentos if a.status in ("agendado", "confirmado"))
        cancelados           = sum(1 for a in agendamentos if a.status == "cancelado")
        faturamento          = sum(float(a.servico.preco) for a in agendamentos if a.status in ("agendado", "confirmado", "concluido"))
        faturamento_realizado = sum(float(a.servico.preco) for a in agendamentos if a.status == "concluido")

        corpo = f"""
        <h2>📊 Resumo do mês — {mes:02d}/{ano}</h2>
        <p>👥 Total: <b>{total}</b> | ✅ Concluídos: <b>{concluidos}</b> | 📅 Agendados: <b>{agendados}</b> | ❌ Cancelados: <b>{cancelados}</b></p>
        <p>💰 Faturamento previsto: <b>R$ {faturamento:.2f}</b></p>
        <p>💰 Faturamento realizado: <b>R$ {faturamento_realizado:.2f}</b></p>
        """

        enviar_email(f"📊 Resumo do mês — {mes:02d}/{ano}", corpo)
        print("[SCHEDULER] Resumo do mês enviado por e-mail.")
    finally:
        db.close()

def lista_dia_seguinte():
    db = SessionLocal()
    try:
        amanha = agora_br() + timedelta(days=1)
        inicio = amanha.replace(hour=0, minute=0, second=0, microsecond=0)
        fim    = inicio + timedelta(hours=24)

        agendamentos = db.query(Agendamento).filter(
            Agendamento.status    == "confirmado",
            Agendamento.data_hora >= inicio,
            Agendamento.data_hora <  fim
        ).order_by(Agendamento.data_hora).all()

        if not agendamentos:
            corpo = f"<h2>📭 Nenhum agendamento para amanhã — {amanha.strftime('%d/%m/%Y')}</h2>"
        else:
            linhas = ""
            for a in agendamentos:
                horario = a.data_hora.strftime("%H:%M")
                linhas += f"<tr><td>{horario}</td><td>{escape(a.cliente.nome)}</td><td>{escape(a.servico.nome)}</td><td>R$ {a.servico.preco}</td></tr>"

            corpo = f"""
            <h2>📅 Agendamentos de amanhã — {amanha.strftime('%d/%m/%Y')}</h2>
            <table border="1" cellpadding="6">
                <tr><th>Horário</th><th>Cliente</th><th>Serviço</th><th>Valor</th></tr>
                {linhas}
            </table>
            """

        enviar_email(f"📅 Agendamentos de amanhã — {amanha.strftime('%d/%m/%Y')}", corpo)
        print("[SCHEDULER] Lista do dia seguinte enviada.")
    finally:
        db.close()

def cancelar_nao_confirmados():
    db = SessionLocal()
    try:
        agora = agora_br()

        # o job dispara às 18h; essa checagem protege caso ele seja chamado antes
        if agora.hour < 18:
            return

        amanha_inicio = (agora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        amanha_fim    = amanha_inicio + timedelta(hours=24)

        # agendamentos de amanhã que a cliente não respondeu
        agendamentos = db.query(Agendamento).filter(
            Agendamento.status    == "agendado",
            Agendamento.data_hora >= amanha_inicio,
            Agendamento.data_hora <  amanha_fim
        ).all()

        cancelados = []
        for ag in agendamentos:
            ag.status = "cancelado"
            cancelados.append(ag)
            print(f"[SCHEDULER] Cancelado por falta de confirmação: {ag.cliente.nome}")

            # avisa a cliente pelo WhatsApp
            try:
                requests.post(BOT_URL, json={
                    "telefone": ag.cliente.telefone,
                    "mensagem": (
                        f"⚠️ Olá {ag.cliente.nome}!\n\n"
                        f"Seu agendamento para {ag.data_hora.strftime('%d/%m/%Y às %H:%M')} "
                        f"foi cancelado pois não recebemos sua confirmação até as 18h.\n\n"
                        f"Para remarcar, entre em contato! 💅"
                    )
                }, timeout=10)
            except Exception as e:
                print(f"[SCHEDULER] Erro ao avisar cliente: {e}")

        db.commit()

        # e-mail para o ateliê com quem foi cancelado
        if cancelados:
            linhas = ""
            for ag in cancelados:
                horario = ag.data_hora.strftime("%H:%M")
                linhas += f"<tr><td>{horario}</td><td>{escape(ag.cliente.nome)}</td><td>{escape(ag.cliente.telefone)}</td></tr>"

            enviar_email(
                f"⚠️ Cancelamentos automáticos — {agora.strftime('%d/%m/%Y')}",
                f"""
                <h2>⚠️ Agendamentos cancelados por falta de confirmação</h2>
                <p>As seguintes clientes não confirmaram até as 18h:</p>
                <table border="1" cellpadding="6">
                    <tr><th>Horário</th><th>Cliente</th><th>Telefone</th></tr>
                    {linhas}
                </table>
                """
            )
    finally:
        db.close()

# Os horários dos jobs abaixo são de Brasília, independente do fuso do servidor
scheduler = BackgroundScheduler(timezone=FUSO)
scheduler.add_job(verificar_lembretes,          "cron", hour=12, minute=45)  # lembrete de amanhã para quem ainda não confirmou
scheduler.add_job(resumo_diario,                "cron", hour=7,  minute=0)   # agenda do dia no WhatsApp do ateliê
scheduler.add_job(lista_dia_seguinte,           "cron", hour=18, minute=0)   # e-mail com os confirmados de amanhã
scheduler.add_job(cancelar_nao_confirmados,     "cron", hour=18, minute=0)   # cancela quem não respondeu o lembrete
scheduler.add_job(resumo_dia_email,             "cron", hour=20, minute=0)   # fechamento do dia
scheduler.add_job(resumo_mes_email,             "cron", hour=20, minute=0, day="last")  # fechamento do mês
scheduler.add_job(concluir_agendamentos_passados, "interval", minutes=30)    # marca como concluído o que já passou
