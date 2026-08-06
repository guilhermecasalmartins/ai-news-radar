from __future__ import annotations

import math
from collections import Counter

from .modelo import Noticia

LIMIAR_DE_JACCARD = 0.5
LIMIAR_DE_SOBREPOSICAO = 0.45
MINIMO_DE_TOKENS_PARTILHADOS = 2
SCORE_MAXIMO = 10.0


COMPRIMENTO_DE_NOME_PROPRIO = 6
FRACAO_MAXIMA_PARA_SER_RARO = 0.05
FREQUENCIA_MINIMA_PARA_SER_RARO = 3


def _tokens_raros(noticias: list[Noticia]) -> set[str]:
    ocorrencias: Counter[str] = Counter()
    for noticia in noticias:
        ocorrencias.update(noticia.tokens)

    limite = max(
        FREQUENCIA_MINIMA_PARA_SER_RARO,
        round(len(noticias) * FRACAO_MAXIMA_PARA_SER_RARO),
    )
    return {
        token
        for token, vezes in ocorrencias.items()
        if vezes <= limite and len(token) >= COMPRIMENTO_DE_NOME_PROPRIO
    }


def _sao_a_mesma_historia(a: Noticia, b: Noticia, raros: set[str]) -> bool:
    ta, tb = a.tokens, b.tokens
    if not ta or not tb:
        return False

    partilhados = ta & tb
    if len(partilhados) < MINIMO_DE_TOKENS_PARTILHADOS:
        return False

    if partilhados & raros:
        return True

    jaccard = len(partilhados) / len(ta | tb)
    sobreposicao = len(partilhados) / min(len(ta), len(tb))
    return jaccard >= LIMIAR_DE_JACCARD or sobreposicao >= LIMIAR_DE_SOBREPOSICAO


def _termos_presentes(texto: str, termos: list[str]) -> list[str]:
    return [t for t in termos if t in texto]


def pontuar(noticia: Noticia, cfg: dict) -> Noticia:
    texto = f"{noticia.titulo} {noticia.resumo_bruto}".lower()
    titulo = noticia.titulo.lower()

    score = 2.0 * noticia.peso_fonte
    motivos = [f"fonte {noticia.fonte} (x{noticia.peso_fonte})"]

    lancamento = cfg.get("sinais_de_lancamento", {})
    if _termos_presentes(titulo, lancamento.get("termos", [])):
        score += lancamento.get("peso", 0)
        motivos.append("sinal de lancamento")

    novidade = cfg.get("sinais_de_novidade", {})
    encontrados = _termos_presentes(texto, novidade.get("termos", []))
    if encontrados:
        intensidade = min(len(encontrados), 3) / 3
        score += novidade.get("peso", 0) * intensidade
        motivos.append(f"novidade ({len(encontrados)} sinais)")

    ruido = cfg.get("sinais_de_ruido", {})
    if _termos_presentes(titulo, ruido.get("termos", [])):
        score += ruido.get("peso", 0)
        motivos.append("ruido detetado")

    if noticia.pontos_hn:
        impulso = min(math.log10(max(noticia.pontos_hn, 1)) - 1.5, 1.5)
        if impulso > 0:
            score += impulso
            motivos.append(f"{noticia.pontos_hn} pontos HN")

    horas = noticia.horas_desde_publicacao
    if horas < 6:
        score += 1.0
        motivos.append("muito recente")
    elif horas < 12:
        score += 0.5

    noticia.score = max(0.0, min(score, SCORE_MAXIMO))
    noticia.motivos = motivos
    return noticia


def remover_duplicados(noticias: list[Noticia]) -> list[Noticia]:
    por_url: dict[str, Noticia] = {}
    for n in noticias:
        existente = por_url.get(n.identidade)
        if existente is None or n.peso_fonte > existente.peso_fonte:
            por_url[n.identidade] = n

    candidatos = sorted(por_url.values(), key=lambda n: n.score, reverse=True)
    raros = _tokens_raros(candidatos)

    mantidos: list[Noticia] = []
    for candidato in candidatos:
        if any(_sao_a_mesma_historia(candidato, guardado, raros) for guardado in mantidos):
            continue
        mantidos.append(candidato)
    return mantidos


def selecionar(noticias: list[Noticia], cfg: dict, ja_enviadas: set[str]) -> list[Noticia]:
    novas = [n for n in noticias if n.identidade not in ja_enviadas]
    pontuadas = [pontuar(n, cfg) for n in novas]
    unicas = remover_duplicados(pontuadas)

    minimo = cfg["config"]["score_minimo"]
    relevantes = [n for n in unicas if n.score >= minimo]
    return sorted(relevantes, key=lambda n: n.score, reverse=True)
