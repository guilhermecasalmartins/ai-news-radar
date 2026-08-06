from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

PALAVRAS_IGNORADAS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "in",
    "is", "it", "its", "of", "on", "or", "that", "the", "to", "was", "were",
    "will", "with", "new", "now", "you", "your",
}

PARAMETROS_DE_TRACKING = re.compile(r"^(utm_|ref$|ref_|source$|fbclid$|gclid$|mc_)")


def _sem_pontuacao(texto: str) -> str:
    return re.sub(r"[^\w\s]", " ", texto.lower())


def tokens_significativos(titulo: str) -> set[str]:
    palavras = _sem_pontuacao(titulo).split()
    return {p for p in palavras if p not in PALAVRAS_IGNORADAS and len(p) > 2}


def url_canonica(url: str) -> str:
    try:
        p = urlparse(url)
        query = "&".join(
            parte for parte in p.query.split("&")
            if parte and not PARAMETROS_DE_TRACKING.match(parte.split("=")[0])
        )
        return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", query, ""))
    except ValueError:
        return url


@dataclass
class Noticia:
    titulo: str
    url: str
    fonte: str
    publicado: datetime
    peso_fonte: float = 1.0
    resumo_bruto: str = ""
    pontos_hn: int = 0
    score: float = 0.0
    motivos: list[str] = field(default_factory=list)
    resumo: str = ""

    @property
    def identidade(self) -> str:
        return hashlib.sha256(url_canonica(self.url).encode()).hexdigest()[:16]

    @property
    def tokens(self) -> set[str]:
        return tokens_significativos(self.titulo)

    @property
    def horas_desde_publicacao(self) -> float:
        agora = datetime.now(timezone.utc)
        return (agora - self.publicado).total_seconds() / 3600
