from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import yaml

from . import correio, llm
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


TIPO_DE_LETRA = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)


def _bloco_html(posicao: int, noticia: Noticia) -> str:
    titulo = correio.escapar(noticia.titulo)
    fonte = correio.escapar(noticia.fonte)
    resumo = (
        f'<div style="font-size:15px;color:#444;line-height:1.5;margin-top:6px;">'
        f"{correio.escapar(noticia.resumo)}</div>"
        if noticia.resumo
        else ""
    )
    return (
        '<div style="margin-bottom:30px;">'
        f'<div style="font-size:12px;color:#8a8a8a;letter-spacing:.04em;text-transform:uppercase;">'
        f"{posicao:02d} &nbsp;·&nbsp; {fonte} &nbsp;·&nbsp; {noticia.score:.1f}/10</div>"
        f'<a href="{correio.escapar(noticia.url)}" '
        'style="display:block;margin-top:5px;font-size:18px;font-weight:600;'
        'color:#111;text-decoration:none;line-height:1.35;">'
        f"{titulo}</a>{resumo}</div>"
    )


def compor_email(noticias: list[Noticia]) -> tuple[str, str, str]:
    agora = datetime.now(timezone.utc)
    data = f"{agora.day} {MESES[agora.month - 1]}"
    periodo = "manha" if agora.hour < 13 else "tarde"

    palavra = "lancamento" if len(noticias) == 1 else "lancamentos"
    assunto = f"AI Radar · {data} · {len(noticias)} {palavra}"

    corpo = "".join(_bloco_html(i, n) for i, n in enumerate(noticias, start=1))
    html = (
        '<!DOCTYPE html><html lang="pt"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;background:#f6f6f6;">'
        f'<div style="max-width:620px;margin:0 auto;background:#fff;padding:28px 22px;'
        f'font-family:{TIPO_DE_LETRA};">'
        '<div style="border-bottom:2px solid #111;padding-bottom:14px;margin-bottom:26px;">'
        '<span style="font-size:21px;font-weight:700;color:#111;">AI Radar</span>'
        f'<span style="font-size:14px;color:#8a8a8a;"> &nbsp;·&nbsp; {data}, {periodo}</span></div>'
        f"{corpo}"
        '<div style="border-top:1px solid #e5e5e5;padding-top:14px;font-size:12px;color:#9a9a9a;">'
        "Curadoria automatica de lancamentos de AI e automacao. "
        "Para receber mais ou menos noticias, ajusta o score_minimo no fontes.yaml."
        "</div></div></body></html>"
    )

    linhas = [f"AI RADAR · {data}, {periodo}", ""]
    for posicao, noticia in enumerate(noticias, start=1):
        linhas.append(f"{posicao:02d}. {noticia.titulo}")
        if noticia.resumo:
            linhas.append(f"    {noticia.resumo}")
        linhas.append(f"    {noticia.fonte} · {noticia.score:.1f}/10")
        linhas.append(f"    {noticia.url}")
        linhas.append("")

    return assunto, html, "\n".join(linhas)


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

    assunto, corpo_html, corpo_texto = compor_email(finais)

    if verboso:
        for n in finais:
            log.info("  %.1f | %s | %s", n.score, n.fonte, n.titulo[:70])
            log.info("       motivos: %s", ", ".join(n.motivos))

    if seco:
        print("\n" + "=" * 70)
        print("MODO SECO - nada foi enviado nem guardado")
        print(f"Assunto: {assunto}")
        print("=" * 70)
        print(corpo_texto)
        return 0

    if not correio.enviar(assunto, corpo_html, corpo_texto):
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
