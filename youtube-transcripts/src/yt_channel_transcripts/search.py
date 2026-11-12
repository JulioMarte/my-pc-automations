"""Busqueda en YouTube (videos, canales, playlists y dentro de un canal) sin API key.

Usa las mismas paginas de resultados que la web de YouTube, a traves de `yt-dlp`.
Los filtros de orden, fecha de subida, tipo y duracion se codifican en el
parametro `sp` de YouTube (un pequeno mensaje protobuf en base64), igual que
cuando se usan los filtros en la web.
"""

from __future__ import annotations

import base64
import itertools
import os
from typing import Any, Callable
from urllib.parse import quote, quote_plus

from . import core

SORTS = {"relevance": 0, "rating": 1, "date": 2, "views": 3}
UPLOAD_DATES = {"hour": 1, "today": 2, "week": 3, "month": 4, "year": 5}
KINDS = {"video": 1, "channel": 2, "playlist": 3}
DURATIONS = {"short": 1, "long": 2, "medium": 3}  # short < 4 min, medium 4-20, long > 20

Searcher = Callable[[str, int], list[dict[str, Any]]]


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def build_sp(kind: str = "video", sort: str = "relevance", upload_date: str | None = None,
             duration: str | None = None) -> str:
    """Parametro `sp` de YouTube. Ej.: solo videos -> 'EgIQAQ=='; videos por fecha -> 'CAISAhAB'."""
    if kind not in KINDS:
        raise ValueError(f"kind debe ser uno de {list(KINDS)}")
    if sort not in SORTS:
        raise ValueError(f"sort debe ser uno de {list(SORTS)}")
    if upload_date is not None and upload_date not in UPLOAD_DATES:
        raise ValueError(f"upload_date debe ser uno de {list(UPLOAD_DATES)}")
    if duration is not None and duration not in DURATIONS:
        raise ValueError(f"duration debe ser uno de {list(DURATIONS)}")
    filters = b""
    if upload_date:
        filters += b"\x08" + _varint(UPLOAD_DATES[upload_date])
    filters += b"\x10" + _varint(KINDS[kind])
    if duration:
        filters += b"\x18" + _varint(DURATIONS[duration])
    msg = (b"\x08" + _varint(SORTS[sort]) if SORTS[sort] else b"") + b"\x12" + _varint(len(filters)) + filters
    return base64.b64encode(msg).decode("ascii")


def search_url(query: str, **kw: Any) -> str:
    return (f"https://www.youtube.com/results?search_query={quote_plus(query)}"
            f"&sp={quote(build_sp(**kw), safe='')}")


def ytdlp_search(url: str, limit: int) -> list[dict[str, Any]]:
    """Primeras `limit` entradas de una pagina de resultados (sin descargar nada)."""
    import yt_dlp

    lang = (os.environ.get("YT_LANGS") or "es").split(",")[0].strip() or "es"
    opts = core._ydl_opts(extract_flat="in_playlist", lazy_playlist=True,
                          extractor_args={"youtube": {"lang": [lang]}})
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False, process=False)
        except Exception as exc:
            if core._is_rate_limit(exc):
                raise core.BlockedError(str(exc)[:200]) from exc
            raise
        return [e for e in itertools.islice(info.get("entries") or [], limit) if e]


def _video(e: dict[str, Any]) -> dict[str, Any]:
    vid = e.get("id")
    return {k: v for k, v in {
        "type": "video", "id": vid, "title": e.get("title"), "url": core.watch_url(vid) if vid else e.get("url"),
        "channel": e.get("channel") or e.get("uploader"), "channel_id": e.get("channel_id"),
        "handle": e.get("uploader_id"), "duration_min": round(e["duration"] / 60, 1) if e.get("duration") else None,
        "views": e.get("view_count"), "description": e.get("description"),
        "live": e.get("live_status") == "is_live" or None,
    }.items() if v is not None}


def _channel(e: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in {
        "type": "channel", "channel_id": e.get("channel_id") or e.get("id"), "channel": e.get("channel") or e.get("title"),
        "handle": e.get("uploader_id"), "url": (f"https://www.youtube.com/{e['uploader_id']}"
                                                if str(e.get("uploader_id") or "").startswith("@") else e.get("url")),
        "subscribers": e.get("channel_follower_count"), "description": e.get("description"),
    }.items() if v is not None}


def _playlist(e: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in {
        "type": "playlist", "id": e.get("id"), "title": e.get("title"), "url": e.get("url"),
        "channel": e.get("channel") or e.get("uploader"), "videos": e.get("playlist_count"),
    }.items() if v is not None}


def search_youtube(query: str, *, kind: str = "video", limit: int = 10, sort: str = "relevance",
                   upload_date: str | None = None, duration: str | None = None,
                   searcher: Searcher = ytdlp_search) -> dict[str, Any]:
    """Busca en todo YouTube. kind: video | channel | playlist."""
    if not query.strip():
        raise ValueError("consulta vacia")
    if duration and kind != "video":
        raise ValueError("duration solo aplica a kind='video'")
    limit = max(1, min(int(limit), 100))
    url = search_url(query, kind=kind, sort=sort, upload_date=upload_date, duration=duration)
    shape = {"video": _video, "channel": _channel, "playlist": _playlist}[kind]
    items = [shape(e) for e in searcher(url, limit)]
    if kind == "video":  # la pagina a veces intercala canales o playlists
        items = [i for i in items if i.get("id") and core.VIDEO_ID_RE.match(i["id"])]
    return {"query": query, "kind": kind, "sort": sort, "returned": len(items), "results": items}


def search_in_channel(channel: str, query: str, *, limit: int = 20,
                      searcher: Searcher = ytdlp_search) -> dict[str, Any]:
    """Usa la busqueda propia del canal en YouTube (titulos y descripciones de TODO el
    canal, sin necesidad de haberlo descargado)."""
    if not query.strip():
        raise ValueError("consulta vacia")
    base = core.channel_url(channel, "videos")
    if "list=" in base:
        raise ValueError("search_in_channel necesita un canal, no una playlist")
    base = base.rsplit("/", 1)[0]
    url = f"{base}/search?query={quote_plus(query)}"
    items = [_video(e) for e in searcher(url, max(1, min(int(limit), 100)))]
    items = [i for i in items if i.get("id") and core.VIDEO_ID_RE.match(i["id"])]
    return {"channel": channel, "query": query, "returned": len(items), "results": items}
