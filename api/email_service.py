import smtplib
from html import escape
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import os

load_dotenv()

REMETENTE    = os.getenv("EMAIL_REMETENTE")
SENHA        = os.getenv("EMAIL_SENHA")
DESTINATARIO = os.getenv("EMAIL_DESTINATARIO")

def enviar_email(assunto: str, corpo: str):
    if not (REMETENTE and SENHA and DESTINATARIO):
        print("[EMAIL] Credenciais não configuradas, e-mail não enviado.")
        return

    try:
        msg = MIMEMultipart()
        msg['From']    = REMETENTE
        msg['To']      = DESTINATARIO
        msg['Subject'] = assunto
        msg.attach(MIMEText(corpo, 'html'))

        # o "with" fecha a conexão mesmo se o envio falhar no meio
        with smtplib.SMTP('smtp.gmail.com', 587) as servidor:
            servidor.starttls()
            servidor.login(REMETENTE, SENHA)
            servidor.sendmail(REMETENTE, DESTINATARIO, msg.as_string())

        print(f"[EMAIL] Enviado: {assunto}")
    except Exception as e:
        # e-mail é só aviso: se falhar, o agendamento não pode falhar junto
        print(f"[EMAIL] Erro ao enviar: {e}")

def email_novo_agendamento(nome: str, telefone: str, servico: str, data_hora: str, valor: float):
    assunto = f"💅 Novo agendamento — {nome}"
    corpo = f"""
    <h2>💅 Novo Agendamento!</h2>
    <table>
        <tr><td><b>👤 Cliente:</b></td><td>{escape(nome)}</td></tr>
        <tr><td><b>📞 Telefone:</b></td><td>{escape(telefone)}</td></tr>
        <tr><td><b>✂️ Serviço:</b></td><td>{escape(servico)}</td></tr>
        <tr><td><b>📅 Data:</b></td><td>{escape(data_hora)}</td></tr>
        <tr><td><b>💰 Valor:</b></td><td>R$ {valor}</td></tr>
    </table>
    """
    enviar_email(assunto, corpo)

def email_cancelamento(nome: str, telefone: str, servico: str, data_hora: str, taxa: bool):
    assunto = f"❌ Cancelamento — {nome}"
    aviso_taxa = "<p><b>⚠️ Cancelamento com menos de 10h — cobrar 50% no próximo agendamento!</b></p>" if taxa else ""
    corpo = f"""
    <h2>❌ Agendamento Cancelado</h2>
    {aviso_taxa}
    <table>
        <tr><td><b>👤 Cliente:</b></td><td>{escape(nome)}</td></tr>
        <tr><td><b>📞 Telefone:</b></td><td>{escape(telefone)}</td></tr>
        <tr><td><b>✂️ Serviço:</b></td><td>{escape(servico)}</td></tr>
        <tr><td><b>📅 Data:</b></td><td>{escape(data_hora)}</td></tr>
    </table>
    """
    enviar_email(assunto, corpo)

def email_atendimento_solicitado(nome: str, telefone: str):
    assunto = f"💬 Atendimento solicitado — {nome}"
    corpo = f"""
    <h2>💬 Atendimento Humano Solicitado!</h2>
    <p>Uma cliente quer falar diretamente com você.</p>
    <table>
        <tr><td><b>👤 Nome:</b></td><td>{escape(nome)}</td></tr>
        <tr><td><b>📞 Telefone:</b></td><td>{escape(telefone)}</td></tr>
    </table>
    <p>Responda diretamente para ela no WhatsApp!</p>
    """
    enviar_email(assunto, corpo)


def email_confirmacao(nome: str, telefone: str, servico: str, data_hora: str):
    assunto = f"✅ Confirmação — {nome}"
    corpo = f"""
    <h2>✅ Agendamento Confirmado!</h2>
    <table>
        <tr><td><b>👤 Cliente:</b></td><td>{escape(nome)}</td></tr>
        <tr><td><b>📞 Telefone:</b></td><td>{escape(telefone)}</td></tr>
        <tr><td><b>💅 Serviço:</b></td><td>{escape(servico)}</td></tr>
        <tr><td><b>📅 Data:</b></td><td>{escape(data_hora)}</td></tr>
    </table>
    """
    enviar_email(assunto, corpo)
