from __future__ import annotations

import json
import logging
import os
import re

import requests

from .modelo import Noticia

log = logging.getLogger(__name__)

TEMPO_LIMITE = 60

MODELOS_POR_OMISSAO = {
    "gemini": "gemini-2.0-flash",
    "groq": "llama-3.3-70b-versatile",
}

INSTRUCOES = """Es um editor de uma newsletter portuguesa sobre AI, especializada em PRODUTOS E LANCAMENTOS.

Recebes uma lista numerada de noticias. Para cada uma, avalia:
- score 0-10: quao relevante e para alguem que quer saber o que foi LANCADO ou ATUALIZADO no mundo da AI e automacao.
  10 = lancamento importante de produto/modelo/API. 
  5 = novidade menor ou atualizacao incremental.
  0 = opiniao, especulacao, noticia de negocio/financeira, tutorial, ou nao e sobre AI.
- resumo: UMA frase em portugues de Portugal (max 20 palavras) que diga concretamente O QUE foi lancado e por quem.
  Nao repitas o titulo. Nao uses "este artigo" nem "a noticia". Vai direto ao facto.

Responde APENAS com JSON valido, sem markdown, no formato:
{"avaliacoes": [{"i": 0, "score": 8.5, "resumo": "..."}, ...]}"""


def _extrair_json(texto: str) -> dict | None:
    limpo = re.sub(r"^```(?:json)?|```$", "", texto.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(limpo)
    except json.JSONDecodeError:
        pass
    inicio, fim = limpo.find("{"), limpo.rfind("}")
    if inicio != -1 and fim > inicio:
        try:
            return json.loads(limpo[inicio : fim + 1])
        except json.JSONDecodeError:
            return None
    return None


def _chamar_gemini(prompt: str, chave: str, modelo: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
    resposta = requests.post(
        url,
        params={"key": chave},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        },
        timeout=TEMPO_LIMITE,
    )
    resposta.raise_for_status()
    return resposta.json()["candidates"][0]["content"]["parts"][0]["text"]


def _chamar_groq(prompt: str, chave: str, modelo: str) -> str:
    resposta = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {chave}"},
        json={
            "model": modelo,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        timeout=TEMPO_LIMITE,
    )
    resposta.raise_for_status()
    return resposta.json()["choices"][0]["message"]["content"]


def esta_configurado() -> bool:
    return bool(os.environ.get("LLM_API_KEY") and os.environ.get("LLM_PROVIDER"))


def refinar(noticias: list[Noticia]) -> list[Noticia]:
    if not noticias or not esta_configurado():
        return noticias

    fornecedor = os.environ["LLM_PROVIDER"].strip().lower()
    chave = os.environ["LLM_API_KEY"].strip()
    modelo = os.environ.get("LLM_MODEL", "").strip() or MODELOS_POR_OMISSAO.get(fornecedor, "")

    if fornecedor not in MODELOS_POR_OMISSAO:
        log.warning("LLM_PROVIDER '%s' desconhecido; a usar so heuristicas", fornecedor)
        return noticias

    listagem = "\n".join(
        f"{i}. [{n.fonte}] {n.titulo}\n   {n.resumo_bruto[:200]}"
        for i, n in enumerate(noticias)
    )
    prompt = f"{INSTRUCOES}\n\nNOTICIAS:\n{listagem}"

    try:
        chamada = _chamar_gemini if fornecedor == "gemini" else _chamar_groq
        bruto = chamada(prompt, chave, modelo)
    except requests.RequestException as erro:
        log.warning("LLM indisponivel (%s); a usar so heuristicas", erro)
        return noticias
    except (KeyError, IndexError) as erro:
        log.warning("resposta inesperada do LLM (%s); a usar so heuristicas", erro)
        return noticias

    dados = _extrair_json(bruto)
    if not dados or "avaliacoes" not in dados:
        log.warning("LLM devolveu JSON invalido; a usar so heuristicas")
        return noticias

    for avaliacao in dados["avaliacoes"]:
        try:
            indice = int(avaliacao["i"])
            noticia = noticias[indice]
        except (KeyError, ValueError, TypeError, IndexError):
            continue

        if "score" in avaliacao:
            try:
                score_llm = float(avaliacao["score"])
            except (TypeError, ValueError):
                score_llm = noticia.score
            noticia.score = round((noticia.score + score_llm * 2) / 3, 2)
            noticia.motivos.append(f"LLM {score_llm}")

        resumo = (avaliacao.get("resumo") or "").strip()
        if resumo:
            noticia.resumo = resumo

    return noticias
