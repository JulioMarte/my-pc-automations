"""Servidor MCP (stdio) sobre la logica de `core`.

Flujo pensado para un modelo:
  harvest_channel (descarga a disco, devuelve solo un resumen)
  -> find_videos (filtra por titulo/descripcion/fecha/duracion)
  -> search_transcripts (busca dentro, con los mismos filtros)
  -> get_transcript (texto paginado en parrafos con minuto).
Asi las transcripciones no inundan el contexto salvo cuando se piden.
"""

from __future__ import annotations

import os
from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer

from . import core
from . import document as ytdoc
from . import catalog as ytcat
from . import pacing as ytpace
from . import search as yts
from . import topic as yttopic

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
5. export_videos: documento final (Markdown y/o PDF) con varios videos -indice, metadatos,
   descripcion, capitulos y transcripcion con [minuto]- para entregar a otro LLM o analizarlo tu.
   Selecciona por video_ids o filtros (incluida query = lo dicho en el video). Incluye TODOS los
   que cumplen el filtro (se parte en archivos de ~100k tokens) y 'coverage' dice cuantos faltan;
   con fetch_missing=true descarga antes los que cumplen el filtro y no tienen transcripcion.
Para un DUMP de un canal sobre un tema (p. ej. "dame todo lo de X sobre Y en PDF") usa el prompt
dump_tema_canal: fetch_metadata (titulo+descripcion de TODO el canal) -> catalog (lees todas las
paginas y juzgas cada video tu mismo) -> selection_update (anotas los elegidos) ->
process_selection (baja solo esas transcripciones y genera UN PDF). find_topic_candidates es un
atajo por palabras cuando no hace falta revisar el canal entero.
Los filtros son por palabras, no por significado. Para respetar la INTENCION del usuario:
 a) traduce la peticion a filtros amplios con sinonimos (p. ej. 'inflacion OR precios OR "costo de vida"'),
 b) revisa los candidatos con find_videos (titulo + descripcion) o search_channel_videos y descarta
    los que no encajan, y
 c) llama export_videos con video_ids = los elegidos. Explica al usuario que criterio usaste.
6. get_video_info: descripcion completa, capitulos, tags. export_channel: jsonl/csv/md del canal.
RITMO: la herramienta limita sola el ritmo y el volumen (presupuesto por hora) y, tras un bloqueo,
se pausa 1 h, 2 h, 4 h... Si 'blocked' trae texto, NO reintentes: informa al usuario de la hora a
partir de la cual se puede seguir (rate_status). Trabajos grandes van en varias tandas."""

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
    languages: preferencia de idioma. Por defecto ["original"] = el idioma en que se habla
      en el video (evita traducciones). ["en"] = ingles si existe, si no el original;
      ["en","es"] = ingles, si no espanol, si no el original. El resultado dice el idioma.
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
    max_videos: int = 500,
    title_filter: str | None = None,
    video_ids: list[str] | None = None,
    refresh_list: bool = False,
    tab: str = "all",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Baja solo metadatos (descripcion, capitulos, tags, fecha exacta) sin transcripcion,
    para poder revisar el canal (catalog) o filtrar por descripcion antes de decidir que transcribir.
    Si el canal no esta en cache, lo lista primero (tab='all' = videos + Shorts + directos).
    ~4-5 s por video (ritmo automatico, presupuesto ~250/hora); reanudable: si 'pending' > 0 y no
    hay 'blocked', vuelve a llamarla. Con YT_API_KEY configurada usa la API oficial (segundos)."""
    st = _store()
    return await anyio.to_thread.run_sync(lambda: core.fetch_metadata(
        st, channel, max_videos=max_videos, title_filter=title_filter, video_ids=video_ids,
        refresh_list=refresh_list, tab=tab, progress=_progress_cb(ctx)))


@mcp.tool()
def catalog(channel: str, offset: int = 0, limit: int = 100, description_chars: int = 400,
            refresh: bool = False) -> dict[str, Any]:
    """Catalogo COMPLETO del canal para que lo revises tu: una linea por video
    'ID | fecha | duracion | titulo | descripcion', paginado (next_offset). Incluye todos los
    videos (tambien Shorts y directos si se listo con tab='all'); los que aun no tienen metadatos
    dicen '(sin descripcion todavia)' -> llama antes fetch_metadata hasta pending=0.
    Lee TODAS las paginas y juzga cada video por su titulo y descripcion."""
    return ytcat.catalog(_store(), channel, offset=offset, limit=limit,
                         description_chars=description_chars, refresh=refresh)


@mcp.tool()
def selection_update(name: str, add: list[str] | None = None, remove: list[str] | None = None,
                     channel: str | None = None, topic: str | None = None,
                     reviewed_until: int | None = None) -> dict[str, Any]:
    """Crea o actualiza una lista de videos elegidos (persistente, en disco). Ve agregando los IDs
    que pasan tu criterio pagina por pagina del catalog. reviewed_until = hasta que posicion del
    catalogo revisaste (para retomar si se interrumpe)."""
    return ytcat.selection_update(_store(), name, add=add, remove=remove, channel=channel, topic=topic,
                                  reviewed_until=reviewed_until)


@mcp.tool()
def selection_show(name: str | None = None) -> Any:
    """Contenido de una lista (ID | estado | titulo) o, sin nombre, todas las listas."""
    st = _store()
    return ytcat.selection_show(st, name) if name else ytcat.selection_list(st)


@mcp.tool()
async def process_selection(name: str, format: str = "pdf", fetch_limit: int = 20,
                            doc_title: str | None = None, max_tokens_per_file: int = 100000,
                            provider: str | None = None) -> dict[str, Any]:
    """Cuando termines de revisar: baja las transcripciones de los videos de la lista (solo esos,
    hasta fetch_limit) y genera el documento (pdf | md | both) con todos, partido en archivos de
    ~max_tokens_per_file tokens sin cortar ningun video (0 = un solo archivo), mas un apendice de
    los que no se pudieron incluir y por que. Reanudable: si YouTube limita la IP, llamala de
    nuevo mas tarde y el documento se regenera completo.
    provider: 'youtube' (defecto, gratis, sujeto a bloqueos de la IP) o 'supadata' (servicio externo:
    1 credito por video en modo native; requiere SUPADATA_API_KEY o el archivo supadata.key)."""
    st = _store()
    if provider:
        os.environ["YT_TRANSCRIPT_PROVIDER"] = provider
    return await anyio.to_thread.run_sync(lambda: ytcat.process_selection(
        st, name, format=format, fetch_limit=fetch_limit, doc_title=doc_title,
        max_tokens_per_file=max_tokens_per_file))


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
async def find_topic_candidates(channel: str, terms: list[str], max_per_term: int = 30,
                                use_youtube_search: bool = True) -> dict[str, Any]:
    """Encuentra los videos de un canal que podrian tratar un tema, buscando por varias vias:
    buscador propio del canal en YouTube (titulos y descripciones de TODO el canal), titulo y
    descripcion en la cache local y lo hablado en transcripciones ya descargadas.

    terms: 3-10 terminos del tema, con sinonimos y variantes (frases se buscan exactas; 'precio*'
      es prefijo). Ej.: ["inflacion", "costo de vida", "precios", "IPC", "devaluacion"].
    Devuelve candidatos con titulo, enlace, fecha, duracion, fragmento de descripcion, si ya tienen
    transcripcion y 'sources' (vias por las que aparecio). NO descarga transcripciones: revisa,
    descarta lo que no encaje y pasa los elegidos a export_videos(video_ids=..., fetch_missing=true)."""
    st = _store()
    r = await anyio.to_thread.run_sync(lambda: yttopic.find_topic_candidates(
        st, channel, terms, max_per_term=max_per_term, use_youtube_search=use_youtube_search))
    return r


@mcp.tool()
def rate_status() -> dict[str, Any]:
    """Estado del limitador: peticiones usadas en la ultima hora, presupuesto, intervalo y si hay
    una pausa activa por bloqueo de YouTube (y hasta cuando)."""
    return ytpace.get_pacer().status()


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
    language: str | None = None,
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
    language: idioma de la transcripcion guardada, p. ej. 'en' o 'es'.
    sort: date_desc | date_asc | relevance | views | duration | title.
    """
    return core.find_videos(_store(), channel, title=title, description=description, text=text,
                            date_from=date_from, date_to=date_to, min_minutes=min_minutes,
                            max_minutes=max_minutes, has_transcript=has_transcript,
                            video_ids=video_ids, language=language, sort=sort, limit=limit, offset=offset)


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
    languages: por defecto la transcripcion guardada (idioma original). Con ["en"] devuelve la
      pista en ingles (la baja y la guarda aparte si hace falta); si no existe, devuelve la
      guardada con un 'note'. Para traducir, mejor traduce tu el original.
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
async def export_videos(
    video_ids: list[str] | None = None,
    channel: str | None = None,
    title: str | None = None,
    description: str | None = None,
    text: str | None = None,
    query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    language: str | None = None,
    limit: int | None = None,
    format: str = "md",
    doc_title: str | None = None,
    include_description: bool = True,
    include_chapters: bool = True,
    max_chars_per_file: int = 400000,
    return_content: bool = False,
    fetch_missing: bool = False,
    fetch_limit: int = 50,
) -> dict[str, Any]:
    """Genera un documento final con varios videos (solo los que tienen transcripcion) para
    entregarlo a otro LLM o analizarlo: indice, canal, fecha, duracion, idioma, enlace,
    descripcion, capitulos y transcripcion en parrafos con [m:ss].

    Seleccion: video_ids (en ese orden) y/o filtros como find_videos; query = lo dicho en el
      video (ordena por relevancia y anota los minutos donde aparece).
    format: md (recomendado para LLM) | pdf (para subir a un chat o leer) | both.
    Por defecto incluye TODOS los que cumplen el filtro (limit=None).
    max_chars_per_file: parte el Markdown en varios archivos sin cortar videos (defecto 400000
      ~ 100k tokens; 0 = un solo archivo).
    fetch_missing: antes de exportar, descarga (hasta fetch_limit) los videos que cumplen el filtro
      y aun no tienen transcripcion; si filtras por descripcion, baja tambien los metadatos que falten.
      Puede tardar ~5 s por video.
    return_content: incluir el Markdown en la respuesta (solo si es corto; si no, lee el archivo
      o el recurso yt://exports/{nombre}).
    Devuelve rutas, tokens aproximados y 'coverage' (cuantos cumplen el filtro, cuantos se incluyeron,
    cuantos no tienen transcripcion y cuantos no se pudieron evaluar por falta de metadatos)."""
    st = _store()
    return await anyio.to_thread.run_sync(lambda: ytdoc.export_videos(
        st, video_ids=video_ids, channel=channel, title=title, description=description, text=text,
        query=query, date_from=date_from, date_to=date_to, language=language, limit=limit, format=format,
        doc_title=doc_title, include_description=include_description, include_chapters=include_chapters,
        max_chars_per_file=max_chars_per_file, return_content=return_content,
        fetch_missing_videos=fetch_missing, fetch_limit=fetch_limit))


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


@mcp.resource("yt://exports/{name}", mime_type="text/markdown")
def export_resource(name: str) -> str:
    """Documento Markdown generado con export_videos (por nombre de archivo)."""
    base = (_store().root / "exports").resolve()
    p = (base / name).resolve()
    if p.parent != base or p.suffix != ".md" or not p.exists():
        return f"No existe el documento {name!r} en {base}."
    return p.read_text(encoding="utf-8")


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
def dump_tema_canal(canal: str, tema: str, formato: str = "pdf") -> str:
    """Dump de un canal sobre un tema: busca, elige y entrega UN solo documento (PDF por defecto)."""
    nombre = f"{canal} {tema}"
    return (
        f"Quiero un unico documento {formato.upper()} con TODOS los videos del canal {canal} que traten sobre: {tema}.\n"
        "Tu decides que videos entran leyendo el titulo y la descripcion de CADA video del canal.\n"
        "Pasos:\n"
        "1. Si no conoces el canal exacto, buscalo con search_youtube(kind='channel') y confirma el @handle.\n"
        f"2. fetch_metadata(channel) y repitela hasta pending=0, para tener titulo y descripcion de todo el canal "
        "(si 'blocked' trae texto, sigue con lo que haya y avisa que hay videos sin descripcion).\n"
        f"3. selection_update(name='{nombre}', channel=<canal>, topic='{tema}').\n"
        "4. Recorre catalog(channel, offset=0, limit=100) pagina por pagina hasta next_offset=null. En cada pagina, "
        f"decide para cada video si trata sobre '{tema}' segun su titulo y descripcion (no solo palabras exactas: "
        "sinonimos, subtemas y videos donde el tema es central). Descarta menciones de paso y publicidad en la "
        f"descripcion. Al terminar cada pagina llama selection_update(name='{nombre}', add=<IDs elegidos>, "
        "reviewed_until=<offset + 100>). No pidas transcripciones todavia.\n"
        f"5. Cuando hayas revisado TODO el catalogo, selection_show('{nombre}') para confirmar la lista.\n"
        f"6. process_selection('{nombre}', format='{formato}', fetch_limit=<total de la lista>).\n"
        "7. Responde con: la ruta del archivo, cuantos videos revisaste, cuantos elegiste y con que criterio, "
        "cuantos entraron al documento y cuales faltan y por que (apendice del documento). Si YouTube limito "
        f"la IP, explica que basta con pedir de nuevo process_selection('{nombre}') mas tarde: se reanuda."
    )


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
