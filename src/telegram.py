from __future__ import annotations

import html
import logging
import os

import requests

log = logging.getLogger(__name__)

LIMITE_DE_CARACTERES = 4000
TEMPO_LIMITE = 30


def escapar(texto: str) -> str:
    return html.escape(texto, quote=False)


def _partir(mensagem: str) -> list[str]:
    if len(mensagem) <= LIMITE_DE_CARACTERES:
        return [mensagem]

    partes, atual = [], ""
    for bloco in mensagem.split("\n\n"):
        if len(atual) + len(bloco) + 2 > LIMITE_DE_CARACTERES:
            if atual:
                partes.append(atual.rstrip())
            atual = bloco + "\n\n"
        else:
            atual += bloco + "\n\n"
    if atual.strip():
        partes.append(atual.rstrip())
    return partes


def credenciais_presentes() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def enviar(mensagem: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    destino = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not destino:
        log.error("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID em falta")
        return False

    for parte in _partir(mensagem):
        try:
            resposta = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": destino,
                    "text": parte,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=TEMPO_LIMITE,
            )
        except requests.RequestException as erro:
            log.error("falha de rede ao enviar para o Telegram: %s", erro)
            return False

        if resposta.status_code != 200:
            log.error("Telegram recusou (%s): %s", resposta.status_code, resposta.text[:300])
            return False

    return True
