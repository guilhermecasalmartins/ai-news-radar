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
    "gemini": "gemini-flash-latest",
    "groq": "llama-3.3-70b-versatile",
}

SEGREDO_NO_URL = re.compile(r"(key=)[^&\s]+")

VARIANTES_ESPECIALIZADAS = (
    "vision", "embedding", "aqa", "tts", "image", "audio", "live",
    "robotics", "learnlm", "gemma", "veo", "imagen",
)

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


def sem_segredos(erro: object) -> str:
    return SEGREDO_NO_URL.sub(r"\1***", str(erro))


def _modelo_inutilizavel(erro: requests.RequestException) -> bool:
    resposta = getattr(erro, "response", None)
    return resposta is not None and resposta.status_code in (400, 404, 429)


def _gerar(fornecedor: str, prompt: str, chave: str, modelo: str) -> str:
    if fornecedor != "gemini":
        return _chamar_groq(prompt, chave, modelo)

    try:
        return _chamar_gemini(prompt, chave, modelo)
    except requests.RequestException as erro:
        if not _modelo_inutilizavel(erro):
            raise
        motivo = getattr(erro.response, "status_code", "?")

    alternativos = [
        m for m in escolher_modelos_gemini(_modelos_gemini_disponiveis(chave)) if m != modelo
    ]
    if not alternativos:
        raise RuntimeError(f"modelo '{modelo}' devolveu {motivo} e nao ha alternativa")

    for alternativo in alternativos[:3]:
        log.info("modelo '%s' devolveu %s; a tentar '%s'", modelo, motivo, alternativo)
        try:
            return _chamar_gemini(prompt, chave, alternativo)
        except requests.RequestException as erro:
            if not _modelo_inutilizavel(erro):
                raise
            log.warning("'%s' tambem falhou: %s", alternativo, sem_segredos(erro))

    raise RuntimeError("nenhum modelo Gemini disponivel aceitou o pedido")


def _modelos_gemini_disponiveis(chave: str) -> list[str]:
    try:
        resposta = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": chave, "pageSize": 200},
            timeout=30,
        )
        resposta.raise_for_status()
        modelos = resposta.json().get("models", [])
    except (requests.RequestException, ValueError) as erro:
        log.warning("nao consegui listar modelos: %s", sem_segredos(erro))
        return []

    return [
        m["name"].split("/")[-1]
        for m in modelos
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]


def _versao(nome: str) -> float:
    encontrado = re.search(r"gemini-(\d+(?:\.\d+)?)", nome)
    return float(encontrado.group(1)) if encontrado else 0.0


def escolher_modelos_gemini(disponiveis: list[str]) -> list[str]:
    utilizaveis = [
        m for m in disponiveis if not any(v in m.lower() for v in VARIANTES_ESPECIALIZADAS)
    ]
    rapidos = [m for m in utilizaveis if "flash" in m] or utilizaveis

    return sorted(
        rapidos,
        key=lambda m: (_versao(m), "preview" not in m, "lite" not in m, -len(m)),
        reverse=True,
    )


def escolher_modelo_gemini(disponiveis: list[str]) -> str:
    escolhidos = escolher_modelos_gemini(disponiveis)
    return escolhidos[0] if escolhidos else ""


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
        bruto = _gerar(fornecedor, prompt, chave, modelo)
    except (requests.RequestException, RuntimeError) as erro:
        log.warning("LLM indisponivel (%s); a usar so heuristicas", sem_segredos(erro))
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
