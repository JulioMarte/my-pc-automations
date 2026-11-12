"""Logica central: listar videos de un canal, bajar transcripciones y guardarlas.

No reinventa nada de YouTube: el listado del canal lo hace `yt-dlp` y las
transcripciones `youtube-transcript-api`. Este modulo solo anade:

- normalizacion de la entrada (@handle, URL, ID de canal),
- seleccion de idioma (manual antes que automatica, en el orden pedido),
- cache en disco incremental y reanudable,
- busqueda y exportacion sobre la cache.

Las dependencias de red se inyectan (`lister`, `fetcher`) para poder probar
toda la logica sin tocar YouTube.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_LANGS = ("es", "en")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
TABS = ("videos", "streams", "shorts")

# Estados de transcripcion guardados por video.
ST_OK = "ok"
ST_NONE = "sin_transcripcion"  # permanente: desactivada, inexistente o video no disponible
ST_ERROR = "error"  # transitorio: se reintenta con retry_errors
ST_PENDING = "pendiente"


class BlockedError(RuntimeError):
    """YouTube bloqueo las peticiones desde esta IP; hay que parar y esperar."""


# ---------------------------------------------------------------------------
# Normalizacion de entradas
# ---------------------------------------------------------------------------

def default_data_dir() -> Path:
    env = os.environ.get("YT_TRANSCRIPTS_DIR")
    return Path(env).expanduser() if env else Path.home() / ".yt-channel-transcripts"


def default_languages() -> list[str]:
    env = os.environ.get("YT_LANGS")
    if env:
        return [x.strip() for x in env.split(",") if x.strip()]
    return list(DEFAULT_LANGS)


def channel_url(channel: str, tab: str = "videos") -> str:
    """Convierte @handle, ID de canal o URL en la URL de la pestana del canal."""
    if tab not in TABS:
        raise ValueError(f"tab debe ser uno de {TABS}")
    c = channel.strip()
    if not c:
        raise ValueError("canal vacio")
    if c.startswith(("http://", "https://")) or c.startswith(("www.", "youtube.com", "m.youtube.com")):
        url = c if c.startswith("http") else "https://" + c
        if "list=" in url:  # playlist: se usa tal cual
            return url
        url = url.split("?")[0].rstrip("/")
        url = re.sub(r"/(videos|streams|shorts|featured|playlists|community|about)$", "", url)
        return f"{url}/{tab}"
    if CHANNEL_ID_RE.match(c):
        return f"https://www.youtube.com/channel/{c}/{tab}"
    handle = c if c.startswith("@") else "@" + c
    return f"https://www.youtube.com/{handle}/{tab}"


def video_id(video: str) -> str:
    """Extrae el ID de 11 caracteres de un ID o URL de video."""
    v = video.strip()
    if VIDEO_ID_RE.match(v):
        return v
    for pat in (r"[?&]v=([A-Za-z0-9_-]{11})", r"youtu\.be/([A-Za-z0-9_-]{11})",
                r"/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})"):
        m = re.search(pat, v)
        if m:
            return m.group(1)
    raise ValueError(f"No reconozco un ID de video en: {video!r}")


def watch_url(vid: str, seconds: float | None = None) -> str:
    url = f"https://www.youtube.com/watch?v={vid}"
    return f"{url}&t={int(seconds)}s" if seconds else url


def fold(text: str) -> str:
    """Minusculas y sin acentos, para buscar sin importar tildes."""
    norm = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in norm if not unicodedata.combining(ch))


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# Adaptadores de red (yt-dlp y youtube-transcript-api)
# ---------------------------------------------------------------------------

def ytdlp_lister(url: str, limit: int | None) -> dict[str, Any]:
    """Lista videos de un canal/playlist sin descargar nada (modo plano)."""
    import yt_dlp

    opts: dict[str, Any] = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_args": {"youtubetab": {"approximate_date": [""]}},
    }
    if limit:
        opts["playlistend"] = limit
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    videos = []
    for e in info.get("entries") or []:
        if not e or not e.get("id") or not VIDEO_ID_RE.match(str(e["id"])):
            continue
        ts = e.get("timestamp") or e.get("release_timestamp")
        date = (datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts
                else _fmt_upload_date(e.get("upload_date")))
        videos.append({
            "id": e["id"],
            "title": e.get("title") or "",
            "url": watch_url(e["id"]),
            "duration": e.get("duration"),
            "date": date,
            "views": e.get("view_count"),
        })
    return {
        "channel_id": info.get("channel_id") or info.get("id"),
        "channel": info.get("channel") or info.get("uploader") or info.get("title"),
        "handle": info.get("uploader_id"),
        "channel_url": info.get("channel_url") or info.get("webpage_url"),
        "videos": videos,
    }


def _fmt_upload_date(d: str | None) -> str | None:
    if d and len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return None


@dataclass
class TranscriptResult:
    status: str
    language: str | None = None
    is_generated: bool | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def pick_transcript(transcripts: Iterable[Any], languages: list[str]) -> Any | None:
    """Elige la mejor pista: manual en idioma pedido > automatica en idioma pedido
    > automatica en el idioma original del video > cualquier manual."""
    items = list(transcripts)
    langs = [lang.lower() for lang in languages]

    def matches(t: Any, lang: str) -> bool:
        code = t.language_code.lower()
        return code == lang or code.split("-")[0] == lang

    for generated in (False, True):
        for lang in langs:
            for t in items:
                if t.is_generated == generated and matches(t, lang):
                    return t
    for t in items:
        if t.is_generated:  # la ASR de YouTube esta en el idioma original
            return t
    return items[0] if items else None


def api_fetcher(vid: str, languages: list[str]) -> TranscriptResult:
    """Baja la transcripcion con youtube-transcript-api."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api import _errors as E

    try:
        api = YouTubeTranscriptApi(proxy_config=_proxy_config())
        chosen = pick_transcript(api.list(vid), languages)
        if chosen is None:
            return TranscriptResult(ST_NONE, error="El video no tiene ninguna pista de subtitulos")
        fetched = chosen.fetch()
        segs = [{"start": round(s.start, 2), "duration": round(s.duration, 2), "text": s.text}
                for s in fetched.snippets]
        return TranscriptResult(ST_OK, chosen.language_code, chosen.is_generated, segs)
    except (E.IpBlocked, E.RequestBlocked) as exc:
        raise BlockedError(str(exc).strip().splitlines()[0] if str(exc).strip() else "IP bloqueada") from exc
    except (E.TranscriptsDisabled, E.NoTranscriptFound, E.VideoUnavailable,
            E.InvalidVideoId, E.AgeRestricted, E.VideoUnplayable) as exc:
        return TranscriptResult(ST_NONE, error=type(exc).__name__)
    except Exception as exc:  # red, parseo, PoToken...: transitorio
        return TranscriptResult(ST_ERROR, error=f"{type(exc).__name__}: {str(exc)[:200]}")


def _proxy_config() -> Any:
    """Proxy opcional para cuando YouTube bloquea la IP (YT_PROXY_HTTP/HTTPS)."""
    http, https = os.environ.get("YT_PROXY_HTTP"), os.environ.get("YT_PROXY_HTTPS")
    if not (http or https):
        return None
    from youtube_transcript_api.proxies import GenericProxyConfig

    return GenericProxyConfig(http_url=http, https_url=https or http)


# ---------------------------------------------------------------------------
# Almacen en disco
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)  # escritura atomica: una interrupcion no corrompe la cache


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


class Store:
    """Estructura:  <root>/<channel_id>/channel.json
                                     /videos.json          (indice, mas reciente primero)
                                     /transcripts/<id>.json
       Videos sueltos (sin canal conocido) van en <root>/_videos/."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else default_data_dir()

    # --- canales -----------------------------------------------------------
    def channels(self) -> list[dict[str, Any]]:
        out = []
        if not self.root.exists():
            return out
        for d in sorted(self.root.iterdir()):
            meta = _read_json(d / "channel.json", None) if d.is_dir() else None
            if meta:
                vids = self.videos(d.name)
                meta = dict(meta)
                meta["videos"] = len(vids)
                meta["with_transcript"] = sum(v.get("status") == ST_OK for v in vids)
                out.append(meta)
        return out

    def resolve(self, channel: str) -> str:
        """Encuentra el channel_id guardado a partir de ID, @handle, nombre o URL."""
        c = channel.strip()
        keys = {fold(c.lstrip("@"))}
        try:  # una URL o @handle tambien se compara contra la URL de origen normalizada
            keys |= {fold(channel_url(c, t)) for t in TABS}
        except ValueError:
            pass
        for meta in self.channels():
            cands = [meta.get("channel_id"), meta.get("handle"), meta.get("channel"),
                     meta.get("channel_url"), meta.get("source")]
            if any(cand and fold(str(cand).lstrip("@").rstrip("/")) in keys for cand in cands):
                return meta["channel_id"]
        raise KeyError(f"Canal no descargado todavia: {channel!r}. Usa harvest_channel primero.")

    def save_channel(self, meta: dict[str, Any]) -> None:
        _write_json(self.root / meta["channel_id"] / "channel.json", meta)

    def videos(self, cid: str) -> list[dict[str, Any]]:
        return _read_json(self.root / cid / "videos.json", [])

    def save_videos(self, cid: str, videos: list[dict[str, Any]]) -> None:
        _write_json(self.root / cid / "videos.json", videos)

    # --- transcripciones ----------------------------------------------------
    def transcript_path(self, cid: str, vid: str) -> Path:
        return self.root / cid / "transcripts" / f"{vid}.json"

    def save_transcript(self, cid: str, video: dict[str, Any], res: TranscriptResult) -> None:
        _write_json(self.transcript_path(cid, video["id"]), {
            "id": video["id"], "title": video.get("title"), "url": video.get("url"),
            "date": video.get("date"), "language": res.language,
            "is_generated": res.is_generated, "fetched_at": _now(), "segments": res.segments,
        })

    def load_transcript(self, vid: str) -> dict[str, Any] | None:
        if not self.root.exists():
            return None
        for d in self.root.iterdir():
            p = d / "transcripts" / f"{vid}.json"
            if p.exists():
                return _read_json(p, None)
        return None


def transcript_text(doc: dict[str, Any], timestamps: bool = False) -> str:
    segs = doc.get("segments") or []
    if timestamps:
        return "\n".join(f"[{fmt_ts(s['start'])}] {s['text']}" for s in segs)
    return " ".join(s["text"].replace("\n", " ") for s in segs)


# ---------------------------------------------------------------------------
# Operaciones de alto nivel
# ---------------------------------------------------------------------------

Lister = Callable[[str, "int | None"], dict[str, Any]]
Fetcher = Callable[[str, list[str]], TranscriptResult]
Progress = Callable[[int, int, str], None]


def harvest(
    store: Store,
    channel: str,
    *,
    max_videos: int = 25,
    list_limit: int | None = None,
    languages: list[str] | None = None,
    tab: str = "videos",
    retry_errors: bool = False,
    delay: float = 1.0,
    lister: Lister = ytdlp_lister,
    fetcher: Fetcher = api_fetcher,
    progress: Progress | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Actualiza el indice del canal y baja hasta `max_videos` transcripciones
    pendientes (de la mas reciente a la mas antigua). Reanudable: lo ya bajado
    no se vuelve a pedir. `list_limit` = cuantos videos recientes listar
    (None = todo el canal)."""
    langs = languages or default_languages()
    source = channel_url(channel, tab)
    listing = lister(source, list_limit)
    cid = listing.get("channel_id")
    if not cid:
        raise RuntimeError(f"yt-dlp no devolvio un ID de canal para {source}")

    store.save_channel({
        "channel_id": cid, "channel": listing.get("channel"), "handle": listing.get("handle"),
        "channel_url": listing.get("channel_url"), "source": source, "updated_at": _now(),
    })

    # Fusionar: conservar estado de lo conocido, anadir lo nuevo arriba.
    known = {v["id"]: v for v in store.videos(cid)}
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for v in listing["videos"]:
        old = known.get(v["id"], {})
        item = {**old, **{k: val for k, val in v.items() if val is not None}}
        item.setdefault("status", ST_PENDING)
        merged.append(item)
        seen.add(v["id"])
    merged += [v for vid, v in known.items() if vid not in seen]  # lo que ya no se listo
    new_count = sum(1 for v in listing["videos"] if v["id"] not in known)

    todo_states = {ST_PENDING} | ({ST_ERROR} if retry_errors else set())
    todo = [v for v in merged if v.get("status") in todo_states][: max(0, max_videos)]

    stats = {ST_OK: 0, ST_NONE: 0, ST_ERROR: 0}
    blocked: str | None = None
    for i, v in enumerate(todo):
        if progress:
            progress(i, len(todo), v.get("title") or v["id"])
        try:
            res = fetcher(v["id"], langs)
        except BlockedError as exc:
            blocked = str(exc)
            break
        v["status"] = res.status
        v["error"] = res.error
        if res.status == ST_OK:
            v["language"] = res.language
            v["is_generated"] = res.is_generated
            v["words"] = sum(len(s["text"].split()) for s in res.segments)
            store.save_transcript(cid, v, res)
        stats[res.status] = stats.get(res.status, 0) + 1
        store.save_videos(cid, merged)  # guardar tras cada video: reanudable
        if delay and i < len(todo) - 1:
            sleep(delay)
    store.save_videos(cid, merged)
    if progress:
        progress(len(todo), len(todo), "listo")

    pending = sum(1 for v in merged if v.get("status") in todo_states)
    return {
        "channel_id": cid,
        "channel": listing.get("channel"),
        "data_dir": str(store.root / cid),
        "listed": len(listing["videos"]),
        "new_videos": new_count,
        "attempted": sum(stats.values()),
        "downloaded": stats[ST_OK],
        "without_transcript": stats[ST_NONE],
        "errors": stats[ST_ERROR],
        "pending": pending,
        "total_with_transcript": sum(1 for v in merged if v.get("status") == ST_OK),
        "blocked": blocked,
        "hint": _harvest_hint(pending, blocked),
    }


def _harvest_hint(pending: int, blocked: str | None) -> str:
    if blocked:
        return ("YouTube bloqueo esta IP. Espera (minutos u horas), baja el ritmo con un delay mayor "
                "o configura YT_PROXY_HTTP/YT_PROXY_HTTPS. Lo ya bajado queda guardado.")
    if pending:
        return f"Quedan {pending} pendientes: vuelve a ejecutar la descarga para continuar."
    return "Completo."


def list_videos(store: Store, channel: str, *, only_with_transcript: bool = False,
                limit: int = 100, offset: int = 0) -> dict[str, Any]:
    cid = store.resolve(channel)
    vids = store.videos(cid)
    if only_with_transcript:
        vids = [v for v in vids if v.get("status") == ST_OK]
    page = vids[offset: offset + limit]
    keys = ("id", "title", "url", "date", "duration", "status", "language", "words")
    return {
        "channel_id": cid, "total": len(vids), "offset": offset,
        "next_offset": offset + limit if offset + limit < len(vids) else None,
        "videos": [{k: v.get(k) for k in keys if v.get(k) is not None} for v in page],
    }


def get_transcript(store: Store, video: str, *, timestamps: bool = False, max_chars: int = 20000,
                   offset: int = 0, languages: list[str] | None = None,
                   fetcher: Fetcher = api_fetcher) -> dict[str, Any]:
    """Devuelve la transcripcion (de la cache o, si no esta, la baja y la guarda
    en `_videos`). Paginada por caracteres para no saturar el contexto."""
    vid = video_id(video)
    doc = store.load_transcript(vid)
    if doc is None:
        res = fetcher(vid, languages or default_languages())
        if res.status != ST_OK:
            return {"id": vid, "url": watch_url(vid), "status": res.status, "error": res.error}
        meta = {"id": vid, "url": watch_url(vid), "title": None, "date": None}
        store.save_transcript("_videos", meta, res)
        doc = store.load_transcript(vid)
        assert doc is not None
    text = transcript_text(doc, timestamps)
    chunk = text[offset: offset + max_chars] if max_chars > 0 else text[offset:]
    end = offset + len(chunk)
    return {
        "id": vid, "title": doc.get("title"), "url": doc.get("url") or watch_url(vid),
        "date": doc.get("date"), "language": doc.get("language"),
        "is_generated": doc.get("is_generated"), "total_chars": len(text),
        "offset": offset, "next_offset": end if end < len(text) else None,
        "transcript": chunk,
    }


def search(store: Store, query: str, *, channel: str | None = None, max_results: int = 20,
           context_chars: int = 160) -> dict[str, Any]:
    """Busqueda literal (sin tildes ni mayusculas) en las transcripciones guardadas.
    Cada resultado trae enlace al segundo exacto."""
    q = fold(query.strip())
    if not q:
        raise ValueError("consulta vacia")
    cids = [store.resolve(channel)] if channel else [c["channel_id"] for c in store.channels()]
    results: list[dict[str, Any]] = []
    total = 0
    for cid in cids:
        for v in store.videos(cid):
            if v.get("status") != ST_OK:
                continue
            doc = _read_json(store.transcript_path(cid, v["id"]), None)
            if not doc:
                continue
            segs = doc["segments"]
            # Texto plano con mapa de offsets -> segmento, para encontrar frases que cruzan segmentos.
            # `flat` (plegado) se usa para buscar; `shown` (original) para el fragmento.
            # Plegar casi siempre conserva la longitud; si no, ese segmento se muestra plegado.
            parts, shown_parts, starts, pos = [], [], [], 0
            for s in segs:
                orig = s["text"].replace("\n", " ") + " "
                t = fold(orig)
                starts.append(pos)
                parts.append(t)
                shown_parts.append(orig if len(orig) == len(t) else t)
                pos += len(t)
            flat, shown = "".join(parts), "".join(shown_parts)
            for m in re.finditer(re.escape(q), flat):
                total += 1
                if len(results) >= max_results:
                    continue
                idx = _bisect(starts, m.start())
                a, b = max(0, m.start() - context_chars), min(len(flat), m.end() + context_chars)
                results.append({
                    "title": v.get("title"), "video_url": v.get("url"),
                    "at": fmt_ts(segs[idx]["start"]), "link": watch_url(v["id"], segs[idx]["start"]),
                    "snippet": ("..." if a else "") + shown[a:b].strip() + ("..." if b < len(flat) else ""),
                })
    return {"query": query, "total_matches": total, "returned": len(results), "results": results}


def _bisect(starts: list[int], pos: int) -> int:
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo


def export(store: Store, channel: str, fmt: str = "jsonl", out: Path | None = None,
           timestamps: bool = False) -> dict[str, Any]:
    """Exporta titulo, enlace, fecha y transcripcion de todos los videos con
    transcripcion. Formatos: jsonl, csv, md."""
    if fmt not in ("jsonl", "csv", "md"):
        raise ValueError("fmt debe ser jsonl, csv o md")
    cid = store.resolve(channel)
    meta = _read_json(store.root / cid / "channel.json", {})
    rows = []
    for v in store.videos(cid):
        if v.get("status") != ST_OK:
            continue
        doc = _read_json(store.transcript_path(cid, v["id"]), None)
        if doc:
            rows.append({"title": v.get("title"), "url": v.get("url"), "date": v.get("date"),
                         "language": doc.get("language"), "transcript": transcript_text(doc, timestamps)})
    path = Path(out) if out else store.root / cid / f"export.{fmt}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "jsonl":
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    elif fmt == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["title", "url", "date", "language", "transcript"])
        w.writeheader()
        w.writerows(rows)
        path.write_text(buf.getvalue(), encoding="utf-8-sig")  # BOM: Excel abre bien los acentos
    else:
        lines = [f"# {meta.get('channel') or cid}\n"]
        for r in rows:
            lines.append(f"\n## {r['title']}\n\n- Enlace: {r['url']}\n- Fecha: {r['date'] or 'desconocida'}\n"
                         f"- Idioma: {r['language']}\n\n{r['transcript']}\n")
        path.write_text("".join(lines), encoding="utf-8")
    return {"channel_id": cid, "format": fmt, "videos": len(rows), "path": str(path)}
