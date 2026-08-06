from __future__ import annotations

import calendar
import concurrent.futures
import html
import logging
import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from .modelo import Noticia

log = logging.getLogger(__name__)

AGENTE = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ai-news-radar/1.0"
TEMPO_LIMITE = 25


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _data_da_entrada(entrada) -> datetime | None:
    for campo in ("published_parsed", "updated_parsed"):
        valor = entrada.get(campo)
        if valor:
            return datetime.fromtimestamp(calendar.timegm(valor), tz=timezone.utc)
    return None


def _texto_curto(entrada) -> str:
    bruto = entrada.get("summary", "") or ""
    sem_tags = re.sub(r"<[^>]+>", " ", bruto)
    sem_entidades = html.unescape(sem_tags)
    return " ".join(sem_entidades.split())[:400]


def _descarregar_feed(url: str) -> feedparser.FeedParserDict | None:
    try:
        resposta = requests.get(url, timeout=TEMPO_LIMITE, headers={"User-Agent": AGENTE})
        resposta.raise_for_status()
        return feedparser.parse(resposta.content)
    except requests.RequestException as erro:
        log.warning("feed inacessivel %s: %s", url, erro)
        return None


def _separar_publisher(entrada, titulo: str) -> tuple[str, str]:
    origem = entrada.get("source") or {}
    publisher = (origem.get("title") or "").strip()

    if publisher and titulo.endswith(f" - {publisher}"):
        return publisher, titulo[: -(len(publisher) + 3)].strip()

    sufixo = re.search(r"\s+-\s+([^-]{2,40})$", titulo)
    if sufixo:
        return sufixo.group(1).strip(), titulo[: sufixo.start()].strip()

    return publisher, titulo


def _noticias_de_feed(
    nome: str, url: str, peso: float, limite: datetime, publisher_na_entrada: bool = False
) -> list[Noticia]:
    feed = _descarregar_feed(url)
    if feed is None:
        return []

    recolhidas = []
    for entrada in feed.entries:
        publicado = _data_da_entrada(entrada)
        if publicado is None or publicado < limite:
            continue
        titulo = (entrada.get("title") or "").strip()
        ligacao = (entrada.get("link") or "").strip()
        if not titulo or not ligacao:
            continue

        fonte = nome
        if publisher_na_entrada:
            publisher, titulo = _separar_publisher(entrada, titulo)
            fonte = publisher or nome

        recolhidas.append(
            Noticia(
                titulo=titulo,
                url=ligacao,
                fonte=fonte,
                publicado=publicado,
                peso_fonte=peso,
                resumo_bruto=_texto_curto(entrada),
            )
        )
    return recolhidas


def recolher_rss(grupos: dict, limite: datetime) -> list[Noticia]:
    fontes = [f for grupo in grupos.values() for f in grupo]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        tarefas = [
            executor.submit(_noticias_de_feed, f["nome"], f["url"], f.get("peso", 1.0), limite)
            for f in fontes
        ]
        return [n for t in concurrent.futures.as_completed(tarefas) for n in t.result()]


def recolher_google_news(cfg: dict, limite: datetime) -> list[Noticia]:
    if not cfg.get("ativo"):
        return []

    peso = cfg.get("peso", 1.0)

    def uma_pesquisa(p: dict) -> list[Noticia]:
        query = urllib.parse.quote(p["query"])
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        return _noticias_de_feed(p["nome"], url, peso, limite, publisher_na_entrada=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        tarefas = [executor.submit(uma_pesquisa, p) for p in cfg.get("pesquisas", [])]
        return [n for t in concurrent.futures.as_completed(tarefas) for n in t.result()]


def recolher_hacker_news(cfg: dict, limite: datetime) -> list[Noticia]:
    if not cfg.get("ativo"):
        return []

    desde = int(limite.timestamp())
    minimo = cfg.get("min_pontos", 100)
    peso = cfg.get("peso", 1.0)
    encontradas: dict[str, Noticia] = {}

    for termo in cfg.get("termos", []):
        parametros = {
            "query": termo,
            "tags": "story",
            "numericFilters": f"points>{minimo},created_at_i>{desde}",
            "hitsPerPage": 40,
        }
        try:
            resposta = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params=parametros,
                timeout=TEMPO_LIMITE,
                headers={"User-Agent": AGENTE},
            )
            resposta.raise_for_status()
            resultados = resposta.json().get("hits", [])
        except (requests.RequestException, ValueError) as erro:
            log.warning("hacker news falhou para '%s': %s", termo, erro)
            continue

        for hit in resultados:
            ligacao = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            titulo = (hit.get("title") or "").strip()
            if not titulo or ligacao in encontradas:
                continue
            encontradas[ligacao] = Noticia(
                titulo=titulo,
                url=ligacao,
                fonte="Hacker News",
                publicado=datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc),
                peso_fonte=peso,
                pontos_hn=hit.get("points", 0),
            )
    return list(encontradas.values())


def _e_patch(etiqueta: str) -> bool:
    versoes = re.findall(r"(\d+)\.(\d+)\.(\d+)", etiqueta)
    if not versoes:
        return False
    return int(versoes[-1][2]) != 0


def recolher_github_releases(cfg: dict, limite: datetime) -> list[Noticia]:
    if not cfg.get("ativo"):
        return []

    cabecalhos = {"User-Agent": AGENTE, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"

    peso = cfg.get("peso", 1.0)

    def ultimo_release(repo: str) -> list[Noticia]:
        try:
            resposta = requests.get(
                f"https://api.github.com/repos/{repo}/releases/latest",
                timeout=TEMPO_LIMITE,
                headers=cabecalhos,
            )
            if resposta.status_code != 200:
                return []
            dados = resposta.json()
        except (requests.RequestException, ValueError) as erro:
            log.warning("github release falhou para %s: %s", repo, erro)
            return []

        if dados.get("draft") or dados.get("prerelease"):
            return []

        publicado_em = dados.get("published_at")
        if not publicado_em:
            return []
        publicado = datetime.strptime(publicado_em, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if publicado < limite:
            return []

        etiqueta = dados.get("tag_name", "")
        if cfg.get("ignorar_patches", True) and _e_patch(etiqueta):
            return []

        projeto = repo.split("/")[-1]
        return [
            Noticia(
                titulo=f"{projeto} {etiqueta} released",
                url=dados.get("html_url", f"https://github.com/{repo}/releases"),
                fonte="GitHub",
                publicado=publicado,
                peso_fonte=peso,
                resumo_bruto=" ".join((dados.get("body") or "").split())[:400],
            )
        ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        tarefas = [executor.submit(ultimo_release, r) for r in cfg.get("repos", [])]
        return [n for t in concurrent.futures.as_completed(tarefas) for n in t.result()]


def recolher_tudo(cfg: dict) -> list[Noticia]:
    limite = _agora() - timedelta(hours=cfg["config"]["janela_horas"])

    tudo: list[Noticia] = []
    tudo += recolher_rss(cfg.get("rss", {}), limite)
    tudo += recolher_google_news(cfg.get("google_news_para_empresas_sem_rss", {}), limite)
    tudo += recolher_hacker_news(cfg.get("hacker_news", {}), limite)
    tudo += recolher_github_releases(cfg.get("github_releases", {}), limite)
    return tudo
