# Nail Studio

Sistema de agendamento feito sob medida para um ateliê de unhas. As clientes
marcam, consultam e cancelam horários conversando com um bot no WhatsApp, e o
ateliê acompanha tudo por um painel web e por avisos automáticos (e-mail e
WhatsApp).

## O que ele faz

- Menu no WhatsApp: ver serviços, agendar, consultar, cancelar, ver endereço e
  pedir atendimento humano
- Agenda com horários fixos (semana e sábado), sem domingos e feriados, sem
  horário duplicado e com no mínimo 4h de antecedência
- Uma cliente só pode ter um agendamento futuro por vez
- Cancelamento com menos de 10h gera cobrança de 50% no próximo atendimento
- Lembrete no dia anterior pedindo confirmação; quem não responde até as 18h
  tem o horário liberado
- Resumo da agenda do dia no WhatsApp do ateliê, e fechamentos diário e mensal
  por e-mail
- Painel web com login: agenda do dia, navegação por data, novo agendamento,
  edição, confirmação, cancelamento e lista de clientes

## Como as partes se falam

```
cliente ──WhatsApp──▶ bot (Node)  ──HTTP──▶ API (FastAPI) ──▶ PostgreSQL
                         ▲                      │
                         └──── lembretes ───────┘  (agendador dentro da API)

painel (HTML/JS) ──JWT──▶ API
```

O bot guarda o passo da conversa de cada cliente na API (tabela `sessoes`), então
um restart não derruba um agendamento pela metade. O agendador da API chama um
servidor HTTP local do bot (porta 3001) para enviar os lembretes, por isso os
dois precisam rodar na mesma máquina (ou ajuste `BOT_URL`).

## Tecnologias

- **API:** Python, FastAPI, SQLAlchemy, APScheduler, PostgreSQL
- **Bot:** Node.js, whatsapp-web.js, axios
- **Painel:** HTML, CSS e JavaScript puro
- **Auth:** JWT para o painel, chave de API (`X-API-Key`) para o bot

## Estrutura

```
api/      FastAPI: rotas, regras de agendamento, agendador, e-mails
bot/      bot do WhatsApp
painel/   painel administrativo (um único index.html)
```

## Como rodar

Pré-requisitos: Python 3.12+, Node 20.6+ e um PostgreSQL.

```bash
cp .env.example .env        # preencha os valores (SECRET_KEY, SENHA_PAINEL, etc.)

# API
cd api
python -m venv venv
source venv/bin/activate    # no Windows: venv\Scripts\activate
pip install -r requirements.txt
python seed.py              # serviços de exemplo (opcional)
uvicorn main:app --reload

# Bot (outro terminal)
cd bot
npm install
npm start                   # escaneie o QR code com o WhatsApp

# Painel
# ajuste a constante API no começo do <script> de painel/index.html
# e abra o arquivo no navegador
```

As tabelas são criadas na primeira subida da API.

## Limitações conhecidas

- O `whatsapp-web.js` não é a API oficial do WhatsApp. Funciona bem para um
  negócio pequeno, mas o número pode ser bloqueado; para algo maior, o caminho é
  a WhatsApp Business API.
- Os feriados são uma lista fixa em `api/main.py` e precisam ser atualizados a
  cada ano.
- A checagem de horário ocupado acontece antes de gravar, sem trava no banco.
  Duas clientes no mesmo segundo ainda podem furar a regra; o ideal é um índice
  único parcial no Postgres.
- Não há testes automatizados no repositório e nem migrations (Alembic).
