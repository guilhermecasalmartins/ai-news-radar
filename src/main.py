from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import yaml

from . import llm, telegram
from .modelo import Noticia
from .recolha import recolher_tudo
from .relevancia import selecionar

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FICHEIRO_DE_ESTADO = RAIZ / "state.json"
FICHEIRO_DE_FONTES = RAIZ / "fontes.yaml"
DIAS_DE_MEMORIA = 21

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

log = logging.getLogger("radar")


def carregar_estado() -> dict:
    if not FICHEIRO_DE_ESTADO.exists():
        return {"enviadas": {}}
    try:
        return json.loads(FICHEIRO_DE_ESTADO.read_text())
    except json.JSONDecodeError:
        log.warning("state.json corrompido; a recomecar")
        return {"enviadas": {}}


def guardar_estado(estado: dict, novas: list[Noticia]) -> None:
    agora = datetime.now(timezone.utc)
    corte = agora - timedelta(days=DIAS_DE_MEMORIA)

    enviadas = {
        identidade: quando
        for identidade, quando in estado.get("enviadas", {}).items()
        if datetime.fromisoformat(quando) > corte
    }
    for noticia in novas:
        enviadas[noticia.identidade] = agora.isoformat()

    FICHEIRO_DE_ESTADO.write_text(
        json.dumps({"enviadas": enviadas}, indent=2, ensure_ascii=False) + "\n"
    )


def compor_mensagem(noticias: list[Noticia]) -> str:
    agora = datetime.now(timezone.utc)
    periodo = "manha" if agora.hour < 13 else "tarde"
    cabecalho = f"<b>AI Radar</b> · {agora.day} {MESES[agora.month - 1]}, {periodo}"

    blocos = [cabecalho]
    for posicao, noticia in enumerate(noticias, start=1):
        titulo = telegram.escapar(noticia.titulo)
        fonte = telegram.escapar(noticia.fonte)
        linhas = [f'{posicao}. <a href="{noticia.url}"><b>{titulo}</b></a>']
        if noticia.resumo:
            linhas.append(telegram.escapar(noticia.resumo))
        linhas.append(f"<i>{fonte} · {noticia.score:.1f}/10</i>")
        blocos.append("\n".join(linhas))

    return "\n\n".join(blocos)


def executar(seco: bool, verboso: bool) -> int:
    cfg = yaml.safe_load(FICHEIRO_DE_FONTES.read_text())
    estado = carregar_estado()
    ja_enviadas = set(estado.get("enviadas", {}))

    log.info("a recolher noticias...")
    recolhidas = recolher_tudo(cfg)
    log.info("%d noticias recolhidas", len(recolhidas))

    relevantes = selecionar(recolhidas, cfg, ja_enviadas)
    log.info("%d relevantes apos dedup e scoring", len(relevantes))

    if not relevantes:
        log.info("nada de novo; nao envio nada")
        return 0

    candidatos = relevantes[: cfg["config"]["max_candidatos_para_reranking_llm"]]
    if llm.esta_configurado():
        log.info("a refinar %d candidatos com LLM...", len(candidatos))
        candidatos = llm.refinar(candidatos)
    else:
        log.info("LLM nao configurado; a usar so heuristicas")

    finais = sorted(candidatos, key=lambda n: n.score, reverse=True)
    finais = [n for n in finais if n.score >= cfg["config"]["score_minimo"]]
    finais = finais[: cfg["config"]["max_por_digest"]]

    if not finais:
        log.info("nada acima do score minimo apos refinamento")
        return 0

    mensagem = compor_mensagem(finais)

    if verboso:
        for n in finais:
            log.info("  %.1f | %s | %s", n.score, n.fonte, n.titulo[:70])
            log.info("       motivos: %s", ", ".join(n.motivos))

    if seco:
        print("\n" + "=" * 70)
        print("MODO SECO - nada foi enviado nem guardado")
        print("=" * 70)
        print(mensagem)
        return 0

    if not telegram.enviar(mensagem):
        return 1

    guardar_estado(estado, finais)
    log.info("digest enviado com %d noticias", len(finais))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AI News Radar")
    parser.add_argument("--seco", action="store_true", help="mostra o digest sem enviar nem guardar estado")
    parser.add_argument("--verboso", action="store_true", help="mostra o scoring de cada noticia")
    argumentos = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-7s %(message)s",
        stream=sys.stderr,
    )
    return executar(seco=argumentos.seco, verboso=argumentos.verboso)


if __name__ == "__main__":
    raise SystemExit(main())
