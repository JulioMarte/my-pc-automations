"""Logica central: listar videos de un canal, bajar metadatos y transcripciones,
guardarlos en disco e indexarlos.

No reinventa nada de YouTube: el listado y los metadatos los da `yt-dlp` y las
transcripciones `youtube-transcript-api` (con `yt-dlp` como respaldo). Este
modulo solo anade:

- normalizacion de la entrada (@handle, URL, ID de canal),
- listado incremental (deja de paginar al llegar a videos ya conocidos),
- seleccion de idioma (manual antes que automatica, en el orden pedido),
- cache en disco incremental y reanudable + indice SQLite FTS5 derivado,
- filtrado por titulo/descripcion, busqueda y exportacion.

Las dependencias de red se inyectan (`lister`, `fetcher`, `enricher`,
`sub_fetcher`) para poder probar toda la logica sin tocar YouTube.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from . import official
from . import pacing
from . import text as T
from .index import Index

ORIGINAL = "original"  # idioma en que se habla en el video
DEFAULT_LANGS = (ORIGINAL,)
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
TABS = ("videos", "streams", "shorts")
ALL_UPLOADS = "all"  # playlist de subidas: videos + Shorts + directos
LIST_TABS = TABS + (ALL_UPLOADS,)
STOP_AFTER_KNOWN = 10  # videos conocidos seguidos que cortan el listado incremental
LOOSE = "_videos"  # carpeta para videos sueltos (sin canal descargado)

# Estados de transcripcion guardados por video.
ST_OK = "ok"
ST_NONE = "sin_transcripcion"  # permanente: desactivada, inexistente o video no disponible
ST_ERROR = "error"  # transitorio: se reintenta con retry_errors
ST_PENDING = "pendiente"

fmt_ts = T.fmt_ts


class BlockedError(RuntimeError):
    """YouTube bloqueo o limito (429) las peticiones desde esta IP; hay que parar."""


# ---------------------------------------------------------------------------
# Normalizacion de entradas
# ---------------------------------------------------------------------------

def default_data_dir() -> Path:
    env = os.environ.get("YT_TRANSCRIPTS_DIR")
    return Path(env).expanduser() if env else Path.home() / ".yt-channel-transcripts"


def lang_base(code: str | None) -> str | None:
    """'es-419' -> 'es'; 'en-orig' -> 'en'."""
    return code.lower().replace("-orig", "").split("-")[0] if code else None


def resolve_languages(languages: list[str], original: str | None) -> list[str]:
    """Sustituye 'original' por el idioma original detectado (si se conoce) y quita
    duplicados, respetando el orden de preferencia."""
    out: list[str] = []
    for lang in languages:
        code = (lang_base(original) if lang.lower() == ORIGINAL else lang.lower())
        if code and code not in out:
            out.append(code)
    return out


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
    """Minusculas y sin acentos, para comparar sin importar tildes."""
    norm = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in norm if not unicodedata.combining(ch))


def _net(cat: str):
    """Aplica ritmo, presupuesto y pausa tras bloqueo (ver pacing.py) a un adaptador de red real."""
    return pacing.paced(cat, BlockedError, lambda e: BlockedError(str(e)))


def _is_rate_limit(exc: BaseException) -> bool:
    s = str(exc)
    return "429" in s or "Too Many Requests" in s or "Sign in to confirm" in s


# ---------------------------------------------------------------------------
# Adaptadores de red: yt-dlp
# ---------------------------------------------------------------------------

def _ydl_opts(**extra: Any) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        # node o deno (si estan instalados) mejoran la extraccion; sin ellos funciona igual.
        "js_runtimes": {"deno": {}, "node": {}},
    }
    opts.update(extra)
    return opts


@_net("page")
def ytdlp_lister(url: str, limit: int | None, known: set[str] | None = None) -> dict[str, Any]:
    """Lista videos de un canal/playlist sin descargar nada, paginando de forma
    perezosa. Con `known`, deja de paginar tras STOP_AFTER_KNOWN videos conocidos
    seguidos (los nuevos siempre salen primero)."""
    import yt_dlp

    opts = _ydl_opts(extract_flat="in_playlist", lazy_playlist=True,
                     extractor_args={"youtubetab": {"approximate_date": [""]}})
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False, process=False)
        except Exception as exc:
            if _is_rate_limit(exc):
                raise BlockedError(str(exc)[:200]) from exc
            raise
        entries = info.get("entries") or []
        videos: list[dict[str, Any]] = []
        streak = 0
        exhausted = True
        stopped_known = False
        it = iter(entries)
        while True:
            if limit and len(videos) >= limit:
                exhausted = next(it, None) is None
                break
            e = next(it, None)
            if e is None:
                break
            if not e or not e.get("id") or not VIDEO_ID_RE.match(str(e["id"])):
                continue
            videos.append(_flat_entry(e))
            if known is not None:
                streak = streak + 1 if e["id"] in known else 0
                if streak >= STOP_AFTER_KNOWN:
                    stopped_known, exhausted = True, False
                    break
    return {
        "channel_id": info.get("channel_id") or info.get("id"),
        "channel": info.get("channel") or info.get("uploader") or info.get("title"),
        "handle": info.get("uploader_id"),
        "channel_url": info.get("channel_url") or info.get("webpage_url"),
        "videos": videos,
        "exhausted": exhausted,  # se recorrio el canal hasta el final
        "stopped_at_known": stopped_known,
    }


def _flat_entry(e: dict[str, Any]) -> dict[str, Any]:
    ts = e.get("timestamp") or e.get("release_timestamp")
    date = (datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts
            else _fmt_upload_date(e.get("upload_date")))
    return {"id": e["id"], "title": e.get("title") or "", "url": watch_url(e["id"]),
            "duration": e.get("duration"), "date": date, "views": e.get("view_count")}


def _fmt_upload_date(d: str | None) -> str | None:
    if d and len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return None


@_net("page")
def ytdlp_video_info(vid: str) -> dict[str, Any]:
    """Metadatos completos de un video (una peticion). Incluye las URLs de subtitulos."""
    import yt_dlp

    with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
        try:
            info = ydl.extract_info(watch_url(vid), download=False)
        except Exception as exc:
            if _is_rate_limit(exc):
                raise BlockedError(str(exc)[:200]) from exc
            raise
        info = ydl.sanitize_info(info)
    return info


def metadata_from_info(info: dict[str, Any]) -> dict[str, Any]:
    chapters = [{"start_time": c.get("start_time"), "end_time": c.get("end_time"), "title": c.get("title")}
                for c in info.get("chapters") or []]
    return {k: v for k, v in {
        "title": info.get("title"),
        "description": info.get("description") or "",
        "tags": info.get("tags") or [],
        "categories": info.get("categories") or [],
        "chapters": chapters,
        "date": _fmt_upload_date(info.get("upload_date")),
        "duration": info.get("duration"),
        "views": info.get("view_count"),
        "likes": info.get("like_count"),
        "language": info.get("language"),
        "channel": info.get("channel"),
        "channel_id": info.get("channel_id"),
    }.items() if v is not None}


@_net("transcript")
def _urlopen_json(url: str) -> Any:
    import yt_dlp

    with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
        return json.loads(ydl.urlopen(url).read().decode("utf-8"))


def subtitles_from_info(info: dict[str, Any], languages: list[str],
                        get_json: Callable[[str], Any] = _urlopen_json) -> "TranscriptResult":
    """Respaldo: subtitulos via yt-dlp (formato json3). Mismo criterio de idioma:
    manual en idioma pedido > automatica original en idioma pedido > automatica
    original en cualquier idioma > cualquier manual. 'original' = idioma de la pista
    automatica original ('xx-orig') o, si no hay, el idioma declarado del video."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    base = lang_base

    origs = [k for k in auto if k.endswith("-orig")] or ([info["language"]] if info.get("language") in auto else [])
    original = base(origs[0]) if origs else base(info.get("language"))
    langs = resolve_languages(languages, original)
    candidates: list[tuple[str, str, bool]] = []
    for lang in langs:
        candidates += [(k, "manual", False) for k in manual if base(k) == lang and k != "live_chat"]
    for lang in langs:
        candidates += [(k, "auto", True) for k in origs if base(k) == lang]
    candidates += [(k, "auto", True) for k in origs]
    candidates += [(k, "manual", False) for k in manual if k != "live_chat"]
    if not candidates:
        return TranscriptResult(ST_NONE, error="yt-dlp: el video no tiene subtitulos")
    key, kind, generated = candidates[0]
    tracks = (manual if kind == "manual" else auto)[key]
    fmt = next((f for f in tracks if f.get("ext") == "json3"), None)
    if not fmt:
        return TranscriptResult(ST_ERROR, error=f"yt-dlp: sin formato json3 para {key}")
    try:
        data = get_json(fmt["url"])
    except Exception as exc:
        if _is_rate_limit(exc):
            raise BlockedError(str(exc)[:200]) from exc
        return TranscriptResult(ST_ERROR, error=f"yt-dlp: {type(exc).__name__}: {str(exc)[:150]}")
    segs = []
    for ev in data.get("events") or []:
        txt = "".join(s.get("utf8", "") for s in ev.get("segs") or []).strip()
        if txt:
            segs.append({"start": round(ev.get("tStartMs", 0) / 1000, 2),
                         "duration": round(ev.get("dDurationMs", 0) / 1000, 2), "text": txt})
    if not segs:
        return TranscriptResult(ST_NONE, error="yt-dlp: subtitulos vacios")
    return TranscriptResult(ST_OK, key.replace("-orig", ""), generated, segs, source="yt-dlp")


# ---------------------------------------------------------------------------
# Adaptador de red: youtube-transcript-api
# ---------------------------------------------------------------------------

@dataclass
class TranscriptResult:
    status: str
    language: str | None = None
    is_generated: bool | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    source: str = "youtube-transcript-api"


def pick_transcript(transcripts: Iterable[Any], languages: list[str]) -> Any | None:
    """Elige la mejor pista: manual en idioma pedido > automatica en idioma pedido
    > automatica en el idioma original del video > cualquier manual.
    'original' en `languages` = idioma de la pista automatica (la ASR de YouTube siempre
    esta en el idioma hablado); asi se evita bajar traducciones subidas como pista manual."""
    items = list(transcripts)
    asr = next((t for t in items if t.is_generated), None)
    langs = resolve_languages(languages, asr.language_code if asr else None)

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


@_net("transcript")
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
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        raise BlockedError(first or type(exc).__name__) from exc
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
# Almacen en disco (fuente de verdad) + indice derivado
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
    """Estructura:  <root>/index.sqlite                 (indice FTS5 derivado)
                    <root>/<channel_id>/channel.json
                                     /videos.json          (indice ligero, mas reciente primero)
                                     /meta/<id>.json       (descripcion, capitulos, tags, fecha exacta)
                                     /transcripts/<id>.json
       Videos sueltos (sin canal descargado) van en <root>/_videos/."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else default_data_dir()
        self._index: Index | None = None

    @property
    def index(self) -> Index:
        if self._index is None:
            self._index = Index(self.root / "index.sqlite")
            if self._index.needs_rebuild:
                rebuild_index(self, self._index)
        return self._index

    def close(self) -> None:
        if self._index is not None:
            self._index.close()
            self._index = None

    # --- canales -----------------------------------------------------------
    def channel_dirs(self) -> list[Path]:
        if not self.root.exists():
            return []
        return [d for d in sorted(self.root.iterdir()) if d.is_dir() and (d / "channel.json").exists()]

    def channel_meta(self, cid: str) -> dict[str, Any]:
        return _read_json(self.root / cid / "channel.json", {})

    def channels(self) -> list[dict[str, Any]]:
        out = []
        for d in self.channel_dirs():
            meta = dict(self.channel_meta(d.name))
            vids = self.videos(d.name)
            meta["videos"] = len(vids)
            meta["with_transcript"] = sum(v.get("status") == ST_OK for v in vids)
            meta["with_metadata"] = sum(bool(v.get("has_metadata")) for v in vids)
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
        for d in self.channel_dirs():
            meta = self.channel_meta(d.name)
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

    # --- por video ------------------------------------------------------------
    def transcript_path(self, cid: str, vid: str) -> Path:
        return self.root / cid / "transcripts" / f"{vid}.json"

    def meta_path(self, cid: str, vid: str) -> Path:
        return self.root / cid / "meta" / f"{vid}.json"

    def save_meta(self, cid: str, vid: str, meta: dict[str, Any]) -> None:
        _write_json(self.meta_path(cid, vid), {"id": vid, "fetched_at": _now(), **meta})

    def save_transcript(self, cid: str, video: dict[str, Any], res: TranscriptResult) -> None:
        _write_json(self.transcript_path(cid, video["id"]), {
            "id": video["id"], "title": video.get("title"), "url": video.get("url"),
            "date": video.get("date"), "language": res.language, "is_generated": res.is_generated,
            "source": res.source, "fetched_at": _now(), "segments": res.segments,
        })

    def variant_path(self, cid: str, vid: str, lang: str) -> Path:
        """Transcripcion adicional en otro idioma (no reemplaza la principal ni se indexa)."""
        return self.root / cid / "transcripts_by_lang" / f"{vid}.{lang}.json"

    def save_variant(self, cid: str, video: dict[str, Any], res: TranscriptResult) -> None:
        _write_json(self.variant_path(cid, video["id"], lang_base(res.language) or "xx"), {
            "id": video["id"], "title": video.get("title"), "url": video.get("url"),
            "date": video.get("date"), "language": res.language, "is_generated": res.is_generated,
            "source": res.source, "fetched_at": _now(), "segments": res.segments,
        })

    def load_variant(self, vid: str, lang: str) -> dict[str, Any] | None:
        if not self.root.exists():
            return None
        for d in self.root.iterdir():
            p = d / "transcripts_by_lang" / f"{vid}.{lang}.json"
            if p.exists():
                return _read_json(p, None)
        return None

    def find_file(self, kind: str, vid: str) -> tuple[str, dict[str, Any]] | None:
        """Busca transcripts/ o meta/ de un video en cualquier canal (incluye _videos)."""
        if not self.root.exists():
            return None
        for d in self.root.iterdir():
            p = d / kind / f"{vid}.json"
            if p.exists():
                return d.name, _read_json(p, {})
        return None

    def load_transcript(self, vid: str) -> dict[str, Any] | None:
        hit = self.find_file("transcripts", vid)
        return hit[1] if hit else None

    def load_meta(self, vid: str) -> dict[str, Any] | None:
        hit = self.find_file("meta", vid)
        return hit[1] if hit else None


def rebuild_index(store: Store, idx: Index | None = None) -> dict[str, Any]:
    """Reconstruye el indice FTS5 desde los JSON (fuente de verdad)."""
    idx = idx or store.index
    idx.clear()
    nv = nc = 0
    for d in store.channel_dirs():
        cid = d.name
        cname = store.channel_meta(cid).get("channel")
        for v in store.videos(cid):
            meta = _read_json(store.meta_path(cid, v["id"]), None)
            idx.upsert_video(cid, cname, v, meta)
            nv += 1
            if v.get("status") == ST_OK:
                doc = _read_json(store.transcript_path(cid, v["id"]), None)
                if doc:
                    idx.set_chunks(v["id"], T.paragraphs(doc["segments"], (meta or {}).get("chapters")))
                    nc += 1
    loose = store.root / LOOSE / "transcripts"
    if loose.exists():
        for p in loose.glob("*.json"):
            doc = _read_json(p, None)
            if doc:
                meta = _read_json(store.meta_path(LOOSE, doc["id"]), None)
                v = {"id": doc["id"], "title": doc.get("title") or (meta or {}).get("title"),
                     "url": doc.get("url"), "status": ST_OK, "language": doc.get("language")}
                idx.upsert_video(LOOSE, (meta or {}).get("channel"), v, meta)
                idx.set_chunks(doc["id"], T.paragraphs(doc["segments"], (meta or {}).get("chapters")))
                nv += 1
                nc += 1
    return {"videos": nv, "transcripts": nc, "path": str(idx.path)}


# ---------------------------------------------------------------------------
# Operaciones de alto nivel
# ---------------------------------------------------------------------------

Lister = Callable[..., dict[str, Any]]
Fetcher = Callable[[str, list[str]], TranscriptResult]
Enricher = Callable[[str], dict[str, Any]]
SubFetcher = Callable[[dict[str, Any], list[str]], TranscriptResult]
Progress = Callable[[int, int, str], None]


def _channel_ref(channel: str) -> str:
    """'@handle' o 'UC...' a partir de lo que escriba el usuario (URL, handle, ID)."""
    c = channel.strip()
    m = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})", c) or re.search(r"(UC[A-Za-z0-9_-]{22})$", c)
    if m:
        return m.group(1)
    m = re.search(r"(@[\w.\-]+)", c)
    if m:
        return m.group(1)
    return "@" + c.lstrip("@")


def _refresh_listing(store: Store, channel: str, tab: str, list_limit: int | None,
                     lister: Lister) -> tuple[str, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Lista el canal (incremental si ya se recorrio completo antes), fusiona con lo
    conocido y actualiza indice y JSON. Devuelve (cid, channel_meta, merged, info)."""
    prev_cid = None
    try:
        prev_cid = store.resolve(channel)
    except KeyError:
        pass
    forced_cid = None
    key = official.api_key()
    use_api = bool(key) and tab == ALL_UPLOADS and lister is ytdlp_lister
    if use_api:  # API oficial: 1 unidad por 50 videos, sin cargar paginas web
        look = official.channel_lookup(prev_cid or _channel_ref(channel), key)
        forced_cid = look["channel_id"]
        source = f"https://www.youtube.com/playlist?list={official.uploads_playlist(forced_cid)}"
    elif tab == ALL_UPLOADS:
        forced_cid = prev_cid
        if not forced_cid:  # averiguar el ID del canal con una pagina minima
            forced_cid = lister(channel_url(channel, "videos"), 1, None).get("channel_id")
        if not forced_cid or not CHANNEL_ID_RE.match(forced_cid):
            raise RuntimeError(f"No pude obtener el ID del canal {channel!r}")
        source = f"https://www.youtube.com/playlist?list=UU{forced_cid[2:]}"
    else:
        source = channel_url(channel, tab)
    prev_meta = store.channel_meta(prev_cid) if prev_cid else {}
    known_list = store.videos(prev_cid) if prev_cid else []
    known = {v["id"]: v for v in known_list}
    incremental = bool(prev_meta.get("listing_complete")) and prev_meta.get("source") == source
    if use_api:
        up = official.list_uploads(forced_cid, key, list_limit, set(known) if incremental else None)
        listing = {"channel_id": forced_cid, "channel": look["channel"], "handle": look["handle"],
                   "channel_url": f"https://www.youtube.com/channel/{forced_cid}", **up}
    else:
        listing = lister(source, list_limit, set(known) if incremental else None)
    cid = forced_cid or listing.get("channel_id")
    if not cid:
        raise RuntimeError(f"yt-dlp no devolvio un ID de canal para {source}")
    complete = bool(prev_meta.get("listing_complete")) or (bool(listing.get("exhausted")) and not list_limit)
    if listing.get("exhausted") and not list_limit:
        complete = True
    cmeta = {"channel_id": cid, "channel": listing.get("channel"), "handle": listing.get("handle"),
             "channel_url": listing.get("channel_url"), "source": source, "updated_at": _now(),
             "listing_complete": complete}
    store.save_channel(cmeta)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    changed: list[dict[str, Any]] = []
    for v in listing["videos"]:
        old = known.get(v["id"])
        item = {**(old or {}), **{k: val for k, val in v.items() if val is not None}}
        if old and old.get("has_metadata"):  # los metadatos exactos ganan al listado aproximado
            for k in ("date", "duration"):
                if old.get(k) is not None:
                    item[k] = old[k]
        item.setdefault("status", ST_PENDING)
        merged.append(item)
        seen.add(v["id"])
        if old is None or old.get("title") != item.get("title"):
            changed.append(item)
    merged += [v for v in known_list if v["id"] not in seen]
    store.save_videos(cid, merged)
    for item in changed:
        store.index.upsert_video(cid, cmeta["channel"], item)
    info = {"listed": len(listing["videos"]), "new_videos": sum(1 for v in listing["videos"] if v["id"] not in known),
            "listing": "incremental" if incremental else ("parcial" if list_limit else "completo"),
            "listing_complete": complete}
    return cid, cmeta, merged, info


def _select(store: Store, cid: str, merged: list[dict[str, Any]], states: set[str],
            title_filter: str | None, video_ids: list[str] | None, need: Callable[[dict], bool]) -> list[dict]:
    allowed: set[str] | None = None
    if video_ids:
        allowed = {video_id(v) for v in video_ids}
    if title_filter:
        found = store.index.find_videos(channel_id=cid, title=title_filter, limit=100000)
        ids = {v["id"] for v in found["videos"]}
        allowed = ids if allowed is None else allowed & ids
    return [v for v in merged if (allowed is None or v["id"] in allowed) and need(v)
            and (v.get("status") in states)]


def _apply_meta(store: Store, cid: str, cname: str | None, v: dict[str, Any], info: dict[str, Any]) -> dict:
    meta = metadata_from_info(info)
    store.save_meta(cid, v["id"], meta)
    v["has_metadata"] = True
    if meta.get("date"):
        v["date"] = meta["date"]
    if meta.get("duration"):
        v["duration"] = meta["duration"]
    if not v.get("title") and meta.get("title"):
        v["title"] = meta["title"]
    store.index.upsert_video(cid, cname, v, meta)
    return meta


def harvest(
    store: Store,
    channel: str,
    *,
    max_videos: int = 20,
    list_limit: int | None = None,
    languages: list[str] | None = None,
    tab: str = "videos",
    retry_errors: bool = False,
    delay: float = 1.0,
    metadata: bool = True,
    title_filter: str | None = None,
    video_ids: list[str] | None = None,
    lister: Lister = ytdlp_lister,
    fetcher: Fetcher = api_fetcher,
    enricher: Enricher = ytdlp_video_info,
    sub_fetcher: SubFetcher = subtitles_from_info,
    progress: Progress | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Actualiza el listado del canal y procesa hasta `max_videos` videos pendientes
    (de mas reciente a mas antiguo): metadatos (descripcion, capitulos, fecha exacta)
    si `metadata`, y transcripcion (youtube-transcript-api; si falla, subtitulos via
    yt-dlp). Reanudable. `title_filter` (sintaxis de busqueda) o `video_ids` limitan
    que videos se procesan."""
    langs = languages or default_languages()
    cid, cmeta, merged, linfo = _refresh_listing(store, channel, tab, list_limit, lister)
    cname = cmeta.get("channel")
    states = {ST_PENDING} | ({ST_ERROR} if retry_errors else set())
    todo = _select(store, cid, merged, states, title_filter, video_ids, lambda v: True)[: max(0, max_videos)]

    stats = {ST_OK: 0, ST_NONE: 0, ST_ERROR: 0}
    sources: dict[str, int] = {}
    meta_count = 0
    blocked: str | None = None
    for i, v in enumerate(todo):
        if progress:
            progress(i, len(todo), v.get("title") or v["id"])
        info: dict[str, Any] | None = None
        meta: dict[str, Any] | None = None
        try:
            if metadata and not v.get("has_metadata"):
                try:
                    info = enricher(v["id"])
                    meta = _apply_meta(store, cid, cname, v, info)
                    meta_count += 1
                except BlockedError:
                    raise
                except Exception as exc:  # metadatos opcionales: no frenan la transcripcion
                    v["meta_error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
            vlangs = langs
            hint = (meta or {}).get("language") or _read_json(store.meta_path(cid, v["id"]), {}).get("language")
            if hint and ORIGINAL in [x.lower() for x in langs]:
                vlangs = langs + [hint]  # respaldo si el video no tiene pista automatica
            # Minimo de peticiones: si ya tenemos la info del video (metadatos), sus URLs de
            # subtitulos permiten bajar la pista con UNA peticion. Si no, la API (2-3 peticiones).
            # Cualquier bloqueo detiene la corrida entera: no se prueba otro endpoint.
            res: TranscriptResult | None = None
            if info is not None:
                res = sub_fetcher(info, vlangs)
            if res is None or res.status == ST_ERROR:
                api_res = fetcher(v["id"], vlangs)
                if res is None or api_res.status != ST_ERROR:
                    res = api_res
            if res.status != ST_OK and info is None and not metadata:
                try:  # sin metadatos: ultimo intento con la info de yt-dlp
                    info = enricher(v["id"])
                    alt = sub_fetcher(info, vlangs)
                    if alt.status == ST_OK:
                        res = alt
                except BlockedError:
                    raise
                except Exception:
                    pass
        except BlockedError as exc:
            blocked = str(exc) or "bloqueado"
            store.save_videos(cid, merged)
            break
        v["status"] = res.status
        v["error"] = res.error
        if res.status == ST_OK:
            v["language"] = res.language
            v["is_generated"] = res.is_generated
            v["words"] = sum(len(s["text"].split()) for s in res.segments)
            v["source"] = res.source
            sources[res.source] = sources.get(res.source, 0) + 1
            store.save_transcript(cid, v, res)
            if meta is None:
                meta = _read_json(store.meta_path(cid, v["id"]), None)
            store.index.set_chunks(v["id"], T.paragraphs(res.segments, (meta or {}).get("chapters")))
        store.index.upsert_video(cid, cname, v, meta)
        stats[res.status] = stats.get(res.status, 0) + 1
        store.save_videos(cid, merged)  # guardar tras cada video: reanudable
        if delay and i < len(todo) - 1:
            sleep(delay)
    store.save_videos(cid, merged)
    if progress:
        progress(len(todo), len(todo), "listo")

    pending = len(_select(store, cid, merged, states, title_filter, video_ids, lambda v: True))
    return {
        "channel_id": cid, "channel": cname, "data_dir": str(store.root / cid), **linfo,
        "attempted": sum(stats.values()), "downloaded": stats[ST_OK],
        "without_transcript": stats[ST_NONE], "errors": stats[ST_ERROR],
        "metadata_fetched": meta_count, "sources": sources, "pending": pending,
        "total_with_transcript": sum(1 for v in merged if v.get("status") == ST_OK),
        "blocked": blocked, "hint": _harvest_hint(pending, blocked),
    }


def fetch_metadata(store: Store, channel: str, *, max_videos: int = 50, title_filter: str | None = None,
                   video_ids: list[str] | None = None, tab: str = "videos", list_limit: int | None = None,
                   refresh_list: bool = False, delay: float = 0.0, concurrency: int = 1,
                   lister: Lister = ytdlp_lister, enricher: Enricher = ytdlp_video_info,
                   progress: Progress | None = None, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Solo metadatos (descripcion, capitulos, tags, fecha exacta), sin transcripcion.
    El ritmo lo pone pacing.py (~4-5 s por video, presupuesto horario); `concurrency` > 1 solo
    para pruebas: en paralelo no se gana nada y se parece mas a un bot. Reanudable.
    Sirve para que el modelo revise titulo + descripcion de todo el canal antes de transcribir."""
    try:
        cid = store.resolve(channel)
        cname = store.channel_meta(cid).get("channel")
        merged = store.videos(cid)
        linfo: dict[str, Any] = {}
    except KeyError:
        refresh_list = True
    if refresh_list:
        cid, cmeta, merged, linfo = _refresh_listing(store, channel, tab, list_limit, lister)
        cname = cmeta.get("channel")
    all_states = {ST_PENDING, ST_OK, ST_NONE, ST_ERROR}
    need = lambda v: not v.get("has_metadata")  # noqa: E731
    todo = _select(store, cid, merged, all_states, title_filter, video_ids, need)[: max(0, max_videos)]
    done = errors = 0
    blocked = None
    key = official.api_key()
    if key and enricher is ytdlp_video_info and todo:  # API oficial: 50 videos por peticion
        try:
            infos = official.videos_info([v["id"] for v in todo], key)
        except official.OfficialAPIError as exc:
            return {"channel_id": cid, "channel": cname, **linfo, "fetched": 0, "errors": len(todo),
                    "pending": len(todo), "blocked": None, "source": "api_oficial", "api_error": str(exc),
                    "hint": "Fallo la API oficial (cuota o clave). Quita YT_API_KEY para usar la via web."}
        for v in todo:
            if v["id"] in infos:
                _apply_meta(store, cid, cname, v, infos[v["id"]])
                v.pop("meta_error", None)
                done += 1
            else:
                v["meta_error"] = "no disponible en la API (privado, borrado o directo programado)"
                errors += 1
        store.save_videos(cid, merged)
        pending = len(_select(store, cid, merged, all_states, title_filter, video_ids, need))
        return {"channel_id": cid, "channel": cname, **linfo, "fetched": done, "errors": errors,
                "pending": pending, "blocked": None, "source": "api_oficial", "hint": _harvest_hint(pending, None)}
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    pending_iter = iter(todo)
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futs: dict[Any, dict[str, Any]] = {}

        def submit_next() -> None:
            v = next(pending_iter, None)
            if v is not None:
                futs[ex.submit(enricher, v["id"])] = v

        for _ in range(max(1, concurrency)):
            submit_next()
        n = 0
        while futs:
            finished, _ = wait(list(futs), return_when=FIRST_COMPLETED)
            for fut in finished:
                v = futs.pop(fut)
                n += 1
                if progress:
                    progress(n - 1, len(todo), v.get("title") or v["id"])
                try:
                    _apply_meta(store, cid, cname, v, fut.result())
                    v.pop("meta_error", None)
                    done += 1
                except BlockedError as exc:
                    blocked = blocked or (str(exc) or "bloqueado")
                except Exception as exc:
                    v["meta_error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
                    errors += 1
                if n % 20 == 0:
                    store.save_videos(cid, merged)
                if not blocked:
                    if delay:
                        sleep(delay)
                    submit_next()
    store.save_videos(cid, merged)
    pending = len(_select(store, cid, merged, all_states, title_filter, video_ids, need))
    return {"channel_id": cid, "channel": cname, **linfo, "fetched": done, "errors": errors,
            "pending": pending, "blocked": blocked, "hint": _harvest_hint(pending, blocked)}


def _harvest_hint(pending: int, blocked: str | None) -> str:
    if blocked:
        return ("YouTube limito o bloqueo esta IP. Espera (minutos u horas), sube el delay "
                "o configura YT_PROXY_HTTP/YT_PROXY_HTTPS. Lo ya bajado queda guardado.")
    if pending:
        return f"Quedan {pending} pendientes: vuelve a ejecutar para continuar."
    return "Completo."


def find_videos(store: Store, channel: str | None = None, **filters: Any) -> dict[str, Any]:
    """Filtra videos en cache por titulo, descripcion, texto (titulo+descripcion+tags),
    fechas, duracion y estado. Ver Index.find_videos."""
    cid = store.resolve(channel) if channel else None
    ids = filters.pop("video_ids", None)
    try:
        return store.index.find_videos(channel_id=cid, video_ids=[video_id(v) for v in ids] if ids else None,
                                       **filters)
    except sqlite3.OperationalError as exc:  # sintaxis FTS5 invalida en un filtro
        raise ValueError(f"Filtro de busqueda invalido ({exc}). Usa palabras sueltas, "
                         '"frase exacta", prefijo*, OR, NOT.') from exc


def get_transcript(store: Store, video: str, *, format: str = "paragraphs", clean: bool = True,
                   max_chars: int = 20000, offset: int = 0, languages: list[str] | None = None,
                   fetcher: Fetcher = api_fetcher, enricher: Enricher = ytdlp_video_info,
                   sub_fetcher: SubFetcher = subtitles_from_info) -> dict[str, Any]:
    """Transcripcion (de la cache o, si no esta, la baja y la guarda en `_videos`).
    Paginada por caracteres para no saturar el contexto."""
    vid = video_id(video)
    hit = store.find_file("transcripts", vid)
    doc = hit[1] if hit else None
    note = None
    if doc is not None and languages and languages[0].lower() != ORIGINAL:
        # Se pidio un idioma concreto: usar la principal si coincide, si no una variante.
        wanted = lang_base(languages[0])
        if lang_base(doc.get("language")) != wanted:
            var = store.load_variant(vid, wanted)
            if var is None:
                langs = resolve_languages(languages, None) or [wanted]
                res = fetcher(vid, langs)
                if res.status == ST_OK and lang_base(res.language) == wanted:
                    store.save_variant(hit[0], doc, res)
                    var = store.load_variant(vid, wanted)
            if var is not None:
                doc = var
            else:
                note = f"No hay pista en '{wanted}'; se devuelve la guardada ({doc.get('language')})."
    if doc is None:
        langs = languages or default_languages()
        res = fetcher(vid, langs)
        info = None
        if res.status != ST_OK:
            try:
                info = enricher(vid)
                alt = sub_fetcher(info, langs)
                res = alt if alt.status == ST_OK else res
            except BlockedError:
                raise
            except Exception:
                pass
        if res.status != ST_OK:
            return {"id": vid, "url": watch_url(vid), "status": res.status, "error": res.error}
        meta = metadata_from_info(info) if info else {}
        if meta:
            store.save_meta(LOOSE, vid, meta)
        v = {"id": vid, "url": watch_url(vid), "title": meta.get("title"), "date": meta.get("date"),
             "status": ST_OK, "language": res.language}
        store.save_transcript(LOOSE, v, res)
        store.index.upsert_video(LOOSE, meta.get("channel"), v, meta or None)
        store.index.set_chunks(vid, T.paragraphs(res.segments, meta.get("chapters")))
        doc = store.load_transcript(vid)
        assert doc is not None
    meta = store.load_meta(vid) or {}
    body = T.render(doc.get("segments") or [], format, meta.get("chapters"), clean)
    chunk = body[offset: offset + max_chars] if max_chars > 0 else body[offset:]
    end = offset + len(chunk)
    return {
        "id": vid, "title": doc.get("title") or meta.get("title"), "url": doc.get("url") or watch_url(vid),
        "date": meta.get("date") or doc.get("date"), "language": doc.get("language"),
        "is_generated": doc.get("is_generated"), "source": doc.get("source"),
        "total_chars": len(body), "offset": offset, "next_offset": end if end < len(body) else None,
        **({"note": note} if note else {}),
        "transcript": chunk,
    }


def get_video_info(store: Store, video: str, *, enricher: Enricher = ytdlp_video_info) -> dict[str, Any]:
    """Metadatos de un video: descripcion completa, capitulos, tags, fecha exacta y
    estado de la transcripcion. Si no estan en cache, los pide a YouTube."""
    vid = video_id(video)
    meta = store.load_meta(vid)
    if meta is None:
        meta = metadata_from_info(enricher(vid))
        hit = store.find_file("transcripts", vid)
        store.save_meta(hit[0] if hit else LOOSE, vid, meta)
    doc = store.load_transcript(vid)
    out = {"id": vid, "url": watch_url(vid), **{k: v for k, v in meta.items() if k not in ("id", "fetched_at")}}
    out["transcript"] = ({"available": True, "language": doc.get("language"), "is_generated": doc.get("is_generated"),
                          "words": sum(len(s["text"].split()) for s in doc.get("segments") or [])}
                         if doc else {"available": False})
    return out


def search(store: Store, query: str, *, channel: str | None = None, max_results: int = 20,
           per_video: int = 3, **filters: Any) -> dict[str, Any]:
    """Busqueda por relevancia (BM25) en las transcripciones indexadas, con filtros
    opcionales de titulo, descripcion, fechas, duracion e IDs."""
    cid = store.resolve(channel) if channel else None
    ids = filters.pop("video_ids", None)
    return store.index.search_chunks(query, channel_id=cid, max_results=max_results, per_video=per_video,
                                     video_ids=[video_id(v) for v in ids] if ids else None, **filters)


def export(store: Store, channel: str, fmt: str = "jsonl", out: Path | None = None,
           format: str = "paragraphs", title_filter: str | None = None) -> dict[str, Any]:
    """Exporta titulo, enlace, fecha, idioma, descripcion y transcripcion de los videos
    con transcripcion (opcionalmente filtrados por titulo). Formatos: jsonl, csv, md."""
    if fmt not in ("jsonl", "csv", "md"):
        raise ValueError("fmt debe ser jsonl, csv o md")
    cid = store.resolve(channel)
    cmeta = store.channel_meta(cid)
    allowed = None
    if title_filter:
        allowed = {v["id"] for v in store.index.find_videos(channel_id=cid, title=title_filter, limit=100000)["videos"]}
    rows = []
    for v in store.videos(cid):
        if v.get("status") != ST_OK or (allowed is not None and v["id"] not in allowed):
            continue
        doc = _read_json(store.transcript_path(cid, v["id"]), None)
        if not doc:
            continue
        meta = _read_json(store.meta_path(cid, v["id"]), {}) or {}
        rows.append({"title": v.get("title"), "url": v.get("url"), "date": v.get("date"),
                     "language": doc.get("language"), "description": meta.get("description", ""),
                     "transcript": T.render(doc["segments"], format, meta.get("chapters"))})
    path = Path(out) if out else store.root / cid / f"export.{fmt}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "jsonl":
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    elif fmt == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["title", "url", "date", "language", "description", "transcript"])
        w.writeheader()
        w.writerows(rows)
        path.write_text(buf.getvalue(), encoding="utf-8-sig")  # BOM: Excel abre bien los acentos
    else:
        lines = [f"# {cmeta.get('channel') or cid}\n"]
        for r in rows:
            desc = f"\n**Descripcion:**\n\n{r['description'].strip()}\n" if r["description"].strip() else ""
            lines.append(f"\n## {r['title']}\n\n- Enlace: {r['url']}\n- Fecha: {r['date'] or 'desconocida'}\n"
                         f"- Idioma: {r['language']}\n{desc}\n{r['transcript']}\n")
        path.write_text("".join(lines), encoding="utf-8")
    return {"channel_id": cid, "format": fmt, "videos": len(rows), "path": str(path)}
