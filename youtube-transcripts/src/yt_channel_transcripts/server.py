"""Servidor MCP (stdio) sobre la logica de `core`.

Flujo pensado para un modelo:
  harvest_channel (descarga a disco, devuelve solo un resumen)
  -> find_videos (filtra por titulo/descripcion/fecha/duracion)
  -> search_transcripts (busca dentro, con los mismos filtros)
  -> get_transcript (texto paginado en parrafos con minuto).
Asi las transcripciones no inundan el contexto salvo cuando se piden.
"""

from __future__ import annotations

from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer

from . import core
from . import search as yts

INSTRUCTIONS = """\
Herramientas para buscar en YouTube y procesar videos y transcripciones de canales (sin API key).
Descubrir (en vivo, sin descargar): search_youtube busca videos, canales o playlists en todo
YouTube (orden, fecha de subida, duracion); search_channel_videos usa el buscador propio de un canal.
Flujo recomendado para trabajar con un canal:
1. harvest_channel: lista el canal y descarga metadatos (descripcion, capitulos) + transcripciones.
   Es incremental; si 'pending' > 0, vuelve a llamarla. Puedes limitarla con title_filter o video_ids.
   Con max_videos=0 solo lista el canal (titulos de todos los videos) sin descargar nada mas.
   Para filtrar por descripcion ANTES de transcribir: fetch_metadata y luego find_videos.
2. find_videos: filtra por title, description, text (titulo+descripcion+tags), fechas, duracion y
   has_transcript. Sintaxis de filtros: palabras (todas deben aparecer), "frase exacta", prefijo*,
   OR, NOT o -palabra. Sin tildes ni mayusculas.
3. search_transcripts: busca dentro de lo hablado, ordenado por relevancia; acepta los mismos filtros.
4. get_transcript: texto en parrafos con [minuto] (paginado con offset/next_offset).
5. get_video_info: descripcion completa, capitulos, tags. export_channel: archivo jsonl/csv/md.
Si 'blocked' trae texto, YouTube limito la IP: no reintentes enseguida."""

mcp = MCPServer("youtube-transcripts", instructions=INSTRUCTIONS)
_STORE: core.Store | None = None


def _store() -> core.Store:
    global _STORE
    root = core.default_data_dir()
    if _STORE is None or _STORE.root != root:
        if _STORE is not None:
            _STORE.close()
        _STORE = core.Store(root)
    return _STORE


def _progress_cb(ctx: Context | None):
    def progress(i: int, n: int, title: str) -> None:
        if ctx is not None and n:
            try:
                anyio.from_thread.run(ctx.report_progress, i, n, title)
            except Exception:
                pass
    return progress


@mcp.tool()
async def harvest_channel(
    channel: str,
    max_videos: int = 20,
    title_filter: str | None = None,
    video_ids: list[str] | None = None,
    list_limit: int | None = None,
    languages: list[str] | None = None,
    metadata: bool = True,
    tab: str = "videos",
    retry_errors: bool = False,
    delay_seconds: float = 1.0,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Descarga metadatos y transcripciones de un canal a la cache local; devuelve un resumen.

    channel: @handle, URL del canal, ID 'UC...' o URL de playlist.
    max_videos: cuantos videos pendientes procesar en esta llamada (mas recientes primero).
    title_filter: procesar solo videos cuyo titulo coincida (p. ej. 'inflacion OR "tasa de interes"').
    video_ids: procesar solo estos IDs/URLs (p. ej. los que devolvio find_videos).
    list_limit: cuantos videos recientes listar en la primera pasada (None = canal completo;
      despues el listado es incremental).
    languages: preferencia de idioma, p. ej. ["es","en"]; manual antes que automatica.
    metadata: bajar tambien descripcion, capitulos, tags y fecha exacta (una peticion extra por video).
    tab: videos | streams | shorts.
    """
    st = _store()
    return await anyio.to_thread.run_sync(lambda: core.harvest(
        st, channel, max_videos=max_videos, list_limit=list_limit, languages=languages, tab=tab,
        retry_errors=retry_errors, delay=delay_seconds, metadata=metadata, title_filter=title_filter,
        video_ids=video_ids, progress=_progress_cb(ctx)))


@mcp.tool()
async def fetch_metadata(
    channel: str,
    max_videos: int = 50,
    title_filter: str | None = None,
    video_ids: list[str] | None = None,
    refresh_list: bool = False,
    delay_seconds: float = 1.0,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Baja solo metadatos (descripcion, capitulos, tags, fecha exacta) sin transcripcion,
    para poder filtrar por descripcion con find_videos antes de decidir que transcribir.
    Si el canal no esta en cache, lo lista primero."""
    st = _store()
    return await anyio.to_thread.run_sync(lambda: core.fetch_metadata(
        st, channel, max_videos=max_videos, title_filter=title_filter, video_ids=video_ids,
        refresh_list=refresh_list, delay=delay_seconds, progress=_progress_cb(ctx)))


def _annotate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Marca que videos/canales ya estan en la cache local."""
    st = _store()
    ids = [i["id"] for i in items if i.get("type") == "video" and i.get("id")]
    status: dict[str, str] = {}
    if ids:
        found = st.index.find_videos(video_ids=ids, limit=len(ids))
        status = {v["id"]: v.get("status") or "listado" for v in found["videos"]}
    cached_channels = {c["channel_id"] for c in st.channels()}
    for i in items:
        if i.get("type") == "video" and i.get("id") in status:
            i["cache_status"] = status[i["id"]]
        if i.get("type") == "channel":
            i["in_cache"] = i.get("channel_id") in cached_channels
    return items


@mcp.tool()
async def search_youtube(query: str, kind: str = "video", limit: int = 10, sort: str = "relevance",
                         upload_date: str | None = None, duration: str | None = None) -> dict[str, Any]:
    """Busca en todo YouTube (en vivo, sin API key).

    kind: video | channel | playlist.
    sort: relevance | date | views | rating.
    upload_date: hour | today | week | month | year (solo lo subido en ese periodo).
    duration: short (<4 min) | medium (4-20) | long (>20); solo para videos.
    Devuelve titulo, enlace, canal (@handle e ID), duracion, vistas y fragmento de descripcion;
    para canales, suscriptores y descripcion. Usa el channel_id o @handle con harvest_channel."""
    r = await anyio.to_thread.run_sync(lambda: yts.search_youtube(
        query, kind=kind, limit=limit, sort=sort, upload_date=upload_date, duration=duration))
    r["results"] = _annotate(r["results"])
    return r


@mcp.tool()
async def search_channel_videos(channel: str, query: str, limit: int = 20) -> dict[str, Any]:
    """Busca dentro de un canal con el buscador propio de YouTube (titulos y descripciones de
    TODO el canal, en vivo, sin haberlo descargado). Util para elegir que videos procesar con
    harvest_channel(video_ids=[...])."""
    r = await anyio.to_thread.run_sync(lambda: yts.search_in_channel(channel, query, limit=limit))
    r["results"] = _annotate(r["results"])
    return r


@mcp.tool()
def list_channels() -> list[dict[str, Any]]:
    """Canales en cache: videos listados, con metadatos y con transcripcion."""
    return _store().channels()


@mcp.tool()
def find_videos(
    channel: str | None = None,
    title: str | None = None,
    description: str | None = None,
    text: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_minutes: float | None = None,
    max_minutes: float | None = None,
    has_transcript: bool | None = None,
    video_ids: list[str] | None = None,
    sort: str = "date_desc",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Filtra videos de la cache y devuelve titulo, enlace, fecha, duracion, estado y un
    fragmento de la descripcion.

    title / description / text: filtros de busqueda sobre el titulo, la descripcion, o ambos
      mas los tags. Palabras sueltas (deben aparecer todas), "frase exacta", prefijo*, OR, NOT.
      No distingue tildes ni mayusculas. La descripcion solo existe si se bajaron metadatos.
    date_from / date_to: 'YYYY-MM-DD'. min_minutes / max_minutes: duracion.
    has_transcript: true = solo con transcripcion; false = solo sin ella.
    sort: date_desc | date_asc | relevance | views | duration | title.
    """
    return core.find_videos(_store(), channel, title=title, description=description, text=text,
                            date_from=date_from, date_to=date_to, min_minutes=min_minutes,
                            max_minutes=max_minutes, has_transcript=has_transcript,
                            video_ids=video_ids, sort=sort, limit=limit, offset=offset)


@mcp.tool()
def search_transcripts(
    query: str,
    channel: str | None = None,
    title: str | None = None,
    description: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    video_ids: list[str] | None = None,
    max_results: int = 20,
    per_video: int = 3,
) -> dict[str, Any]:
    """Busca en lo hablado en los videos (ordenado por relevancia). Devuelve titulo,
    capitulo, enlace al segundo exacto y fragmento con la coincidencia en **negrita**.
    query: palabras, "frase exacta", prefijo*, OR, NOT. Filtros opcionales como en find_videos.
    per_video: maximo de fragmentos por video."""
    return core.search(_store(), query, channel=channel, title=title, description=description,
                       date_from=date_from, date_to=date_to, video_ids=video_ids,
                       max_results=max_results, per_video=per_video)


@mcp.tool()
async def get_transcript(video: str, format: str = "paragraphs", clean: bool = True,
                         max_chars: int = 20000, offset: int = 0,
                         languages: list[str] | None = None) -> dict[str, Any]:
    """Transcripcion de un video (ID o URL). Si no esta en cache la descarga.
    format: paragraphs ('[1:05] texto' por parrafo, con titulos de capitulo) | text | segments.
    clean: quita etiquetas como [Musica] y lineas repetidas.
    Paginada: si next_offset no es null, vuelve a llamar con offset=next_offset."""
    st = _store()
    return await anyio.to_thread.run_sync(lambda: core.get_transcript(
        st, video, format=format, clean=clean, max_chars=max_chars, offset=offset, languages=languages))


@mcp.tool()
async def get_video_info(video: str) -> dict[str, Any]:
    """Metadatos de un video: titulo, descripcion completa, capitulos, tags, fecha exacta,
    duracion, vistas y si hay transcripcion. Si no estan en cache, los pide a YouTube."""
    st = _store()
    return await anyio.to_thread.run_sync(lambda: core.get_video_info(st, video))


@mcp.tool()
def export_channel(channel: str, format: str = "jsonl", text_format: str = "paragraphs",
                   title_filter: str | None = None) -> dict[str, Any]:
    """Exporta titulo, enlace, fecha, idioma, descripcion y transcripcion de los videos con
    transcripcion (opcionalmente solo los que coinciden con title_filter) a un archivo
    jsonl, csv o md dentro de la cache, y devuelve la ruta."""
    return core.export(_store(), channel, format, format=text_format, title_filter=title_filter)


@mcp.tool()
def rebuild_index() -> dict[str, Any]:
    """Reconstruye el indice de busqueda desde los archivos de la cache (si algo no aparece
    en find_videos o search_transcripts)."""
    return core.rebuild_index(_store())


# --- recursos y prompts ---------------------------------------------------------

@mcp.resource("yt://video/{video_id}", mime_type="text/markdown")
def video_resource(video_id: str) -> str:
    """Transcripcion completa en Markdown (de la cache) con titulo, enlace y descripcion."""
    st = _store()
    doc = st.load_transcript(core.video_id(video_id))
    if doc is None:
        return f"El video {video_id} no tiene transcripcion en cache. Usa get_transcript."
    meta = st.load_meta(doc["id"]) or {}
    body = core.get_transcript(st, doc["id"], max_chars=0)["transcript"]
    desc = (meta.get("description") or "").strip()
    return (f"# {doc.get('title') or meta.get('title') or doc['id']}\n\n{doc.get('url')}\n\n"
            + (f"## Descripcion\n\n{desc}\n\n" if desc else "") + f"## Transcripcion\n\n{body}\n")


@mcp.resource("yt://channels", mime_type="application/json")
def channels_resource() -> list[dict[str, Any]]:
    """Canales en cache."""
    return _store().channels()


@mcp.prompt()
def investigar_tema(channel: str, tema: str) -> str:
    """Investiga que dice un canal sobre un tema, citando videos y minutos."""
    return (f"Investiga que dice el canal {channel} sobre: {tema}.\n"
            "1. Si el canal no esta en cache (list_channels), usa harvest_channel.\n"
            "   Si no sabes el canal exacto, buscalo con search_youtube(kind='channel').\n"
            f"2. Usa find_videos con text='{tema}' para candidatos por titulo/descripcion, y "
            f"search_transcripts con query='{tema}' para lo hablado.\n"
            "3. Lee con get_transcript solo los fragmentos necesarios.\n"
            "4. Responde con un resumen y cita cada afirmacion con [titulo](enlace con &t=).")


@mcp.prompt()
def resumir_video(video: str) -> str:
    """Resume un video por capitulos, con minutos."""
    return (f"Resume el video {video}. Usa get_video_info (descripcion y capitulos) y get_transcript "
            "(paginando si next_offset no es null). Da un resumen de 5 lineas y luego los puntos "
            "clave por capitulo con su minuto [m:ss].")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
