from __future__ import annotations

import html
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger(__name__)

SERVIDOR = "smtp.gmail.com"
PORTA = 465
TEMPO_LIMITE = 45


def escapar(texto: str) -> str:
    return html.escape(texto, quote=True)


def credenciais_presentes() -> bool:
    return all(
        os.environ.get(chave)
        for chave in ("SMTP_UTILIZADOR", "SMTP_PASSWORD", "EMAIL_DESTINO")
    )


def enviar(assunto: str, corpo_html: str, corpo_texto: str) -> bool:
    utilizador = os.environ.get("SMTP_UTILIZADOR", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    destino = os.environ.get("EMAIL_DESTINO", "").strip()

    if not utilizador or not password or not destino:
        log.error("SMTP_UTILIZADOR, SMTP_PASSWORD ou EMAIL_DESTINO em falta")
        return False

    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = f"AI News Radar <{utilizador}>"
    mensagem["To"] = destino
    mensagem.set_content(corpo_texto)
    mensagem.add_alternative(corpo_html, subtype="html")

    try:
        contexto = ssl.create_default_context()
        with smtplib.SMTP_SSL(SERVIDOR, PORTA, context=contexto, timeout=TEMPO_LIMITE) as servidor:
            servidor.login(utilizador, password)
            servidor.send_message(mensagem)
    except smtplib.SMTPAuthenticationError:
        log.error(
            "credenciais SMTP recusadas. Confirma que SMTP_PASSWORD e uma "
            "App Password do Google (16 caracteres) e nao a password normal da conta"
        )
        return False
    except (smtplib.SMTPException, OSError) as erro:
        log.error("falha ao enviar email: %s", erro)
        return False

    log.info("email entregue a %s", destino)
    return True
