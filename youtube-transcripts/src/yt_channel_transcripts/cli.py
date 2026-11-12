"""CLI equivalente a las herramientas MCP, para usarlo sin un cliente MCP.

    yt-transcripts youtube "consulta" [--kind video|channel|playlist] [--sort date] [--upload-date week]
    yt-transcripts channel-search @canal "consulta"
    yt-transcripts harvest @canal --max 50 [--all] [--title "inflacion OR precios"]
    yt-transcripts metadata @canal --max 100
    yt-transcripts channels
    yt-transcripts find [--channel @canal] [--title ...] [--description ...] [--text ...]
    yt-transcripts get <url|id> [--format paragraphs|text|segments]
    yt-transcripts info <url|id>
    yt-transcripts search "frase" [--channel @canal] [--title ...]
    yt-transcripts export @canal --format md|jsonl|csv [--out ruta]
    yt-transcripts doc [--ids ...] [--channel @c] [--query "..."] [--format md|pdf|both]
    yt-transcripts reindex
    yt-transcripts serve            # servidor MCP por stdio
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import core
from . import document as ytdoc
from . import catalog as ytcat
from . import pacing as ytpace
from . import search as yts
from . import topic as yttopic


def _print(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _progress(i: int, n: int, title: str) -> None:
    if i < n:
        print(f"  [{i + 1}/{n}] {title}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # consola de Windows: evitar errores con acentos
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    p = argparse.ArgumentParser(prog="yt-transcripts", description="Transcripciones de canales de YouTube")
    p.add_argument("--data-dir", help="carpeta de cache (por defecto YT_TRANSCRIPTS_DIR o ~/.yt-channel-transcripts)")
    sub = p.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest", help="listar el canal y bajar metadatos + transcripciones")
    h.add_argument("channel")
    h.add_argument("--max", type=int, default=20, help="videos a procesar en esta corrida")
    h.add_argument("--title", help="procesar solo titulos que coincidan (sintaxis de busqueda)")
    h.add_argument("--ids", nargs="*", help="procesar solo estos IDs/URLs")
    h.add_argument("--list-limit", type=int, default=None, help="videos recientes a listar (1a pasada)")
    h.add_argument("--all", action="store_true", help="seguir en tandas hasta terminar")
    h.add_argument("--lang", default=None, help="idiomas preferidos: original (defecto), en, es,en...")
    h.add_argument("--no-metadata", action="store_true", help="no bajar descripcion/capitulos")
    h.add_argument("--tab", default="videos", choices=core.LIST_TABS)
    h.add_argument("--retry-errors", action="store_true")
    h.add_argument("--delay", type=float, default=1.0)

    m = sub.add_parser("metadata", help="bajar solo metadatos (descripcion, capitulos, fecha)")
    m.add_argument("channel")
    m.add_argument("--max", type=int, default=50)
    m.add_argument("--title")
    m.add_argument("--refresh-list", action="store_true")
    m.add_argument("--tab", default="all", choices=core.LIST_TABS)


    sub.add_parser("channels", help="canales en cache")

    f = sub.add_parser("find", help="filtrar videos por titulo/descripcion/fecha/duracion")
    f.add_argument("--channel")
    f.add_argument("--title")
    f.add_argument("--description")
    f.add_argument("--text", help="titulo + descripcion + tags")
    f.add_argument("--from", dest="date_from")
    f.add_argument("--to", dest="date_to")
    f.add_argument("--min-minutes", type=float)
    f.add_argument("--max-minutes", type=float)
    f.add_argument("--with-transcript", action="store_true")
    f.add_argument("--language", help="idioma de la transcripcion guardada (en, es...)")
    f.add_argument("--sort", default="date_desc")
    f.add_argument("--limit", type=int, default=50)

    g = sub.add_parser("get", help="transcripcion de un video")
    g.add_argument("video")
    g.add_argument("--format", default="paragraphs", choices=("paragraphs", "text", "segments"))
    g.add_argument("--raw", action="store_true", help="sin limpiar etiquetas [Musica]")
    g.add_argument("--lang", default=None)

    i = sub.add_parser("info", help="metadatos de un video")
    i.add_argument("video")

    s = sub.add_parser("search", help="buscar en las transcripciones")
    s.add_argument("query")
    s.add_argument("--channel")
    s.add_argument("--title")
    s.add_argument("--description")
    s.add_argument("--max", type=int, default=20)

    e = sub.add_parser("export", help="exportar titulo+enlace+descripcion+transcripcion")
    e.add_argument("channel")
    e.add_argument("--format", default="jsonl", choices=("jsonl", "csv", "md"))
    e.add_argument("--text-format", default="paragraphs", choices=("paragraphs", "text", "segments"))
    e.add_argument("--title")
    e.add_argument("--out")

    y = sub.add_parser("youtube", help="buscar videos, canales o playlists en YouTube (en vivo)")
    y.add_argument("query")
    y.add_argument("--kind", default="video", choices=list(yts.KINDS))
    y.add_argument("--sort", default="relevance", choices=list(yts.SORTS))
    y.add_argument("--upload-date", choices=list(yts.UPLOAD_DATES))
    y.add_argument("--duration", choices=list(yts.DURATIONS))
    y.add_argument("--limit", type=int, default=10)

    cs = sub.add_parser("channel-search", help="buscador propio de un canal (en vivo)")
    cs.add_argument("channel")
    cs.add_argument("query")
    cs.add_argument("--limit", type=int, default=20)

    d = sub.add_parser("doc", help="documento MD/PDF con varios videos para un LLM")
    d.add_argument("--ids", nargs="*")
    d.add_argument("--channel")
    d.add_argument("--title")
    d.add_argument("--description")
    d.add_argument("--text")
    d.add_argument("--query", help="lo dicho en el video")
    d.add_argument("--from", dest="date_from")
    d.add_argument("--to", dest="date_to")
    d.add_argument("--language")
    d.add_argument("--limit", type=int, default=None, help="maximo de videos (defecto: todos)")
    d.add_argument("--format", default="md", choices=("md", "pdf", "both"))
    d.add_argument("--doc-title")
    d.add_argument("--no-description", action="store_true")
    d.add_argument("--max-chars", type=int, default=400000, help="partir el MD (defecto ~100k tokens; 0 = no)")
    d.add_argument("--fetch-missing", action="store_true", help="descargar antes lo que falte")
    d.add_argument("--fetch-limit", type=int, default=50)
    d.add_argument("--out-dir")
    d.add_argument("--name", help="nombre de archivo sin extension")

    tp = sub.add_parser("topic", help="candidatos de un canal para un tema (varias vias)")
    tp.add_argument("channel")
    tp.add_argument("terms", nargs="+")
    tp.add_argument("--max-per-term", type=int, default=30)
    tp.add_argument("--no-youtube", action="store_true")

    cg = sub.add_parser("catalog", help="catalogo del canal: ID | fecha | duracion | titulo | descripcion")
    cg.add_argument("channel")
    cg.add_argument("--offset", type=int, default=0)
    cg.add_argument("--limit", type=int, default=100)
    cg.add_argument("--chars", type=int, default=400)
    cg.add_argument("--refresh", action="store_true")

    sl = sub.add_parser("select", help="lista de seleccion: agregar/quitar/ver")
    sl.add_argument("name", nargs="?")
    sl.add_argument("--add", nargs="*")
    sl.add_argument("--remove", nargs="*")
    sl.add_argument("--channel")
    sl.add_argument("--topic")

    pr = sub.add_parser("process", help="transcripciones de la lista + documento unico")
    pr.add_argument("name")
    pr.add_argument("--format", default="pdf", choices=("md", "pdf", "both"))
    pr.add_argument("--fetch-limit", type=int, default=20)
    pr.add_argument("--max-tokens", type=int, default=100000, help="por archivo (0 = un solo archivo)")

    pc = sub.add_parser("pacing", help="estado del limitador (o --reset tras cambiar de red)")
    pc.add_argument("--reset", action="store_true")

    sub.add_parser("reindex", help="reconstruir el indice de busqueda")
    sub.add_parser("serve", help="servidor MCP por stdio")

    # IDs de YouTube que empiezan por "-" (p. ej. -VCdtSAtSUU) se confunden con opciones:
    # se convierten a URL antes de parsear. Las opciones largas empiezan por "--".
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = [core.watch_url(t) if (t.startswith("-") and not t.startswith("--") and core.VIDEO_ID_RE.match(t))
            else t for t in argv]
    a = p.parse_args(argv)
    if a.cmd == "serve":
        from .server import main as serve
        serve()
        return 0
    store = core.Store(Path(a.data_dir) if a.data_dir else None)
    langs = [x.strip() for x in a.lang.split(",")] if getattr(a, "lang", None) else None
    try:
        if a.cmd == "harvest":
            while True:
                r = core.harvest(store, a.channel, max_videos=a.max, list_limit=a.list_limit, languages=langs,
                                 tab=a.tab, retry_errors=a.retry_errors, delay=a.delay,
                                 metadata=not a.no_metadata, title_filter=a.title, video_ids=a.ids,
                                 progress=_progress)
                _print(r)
                if not a.all or r["blocked"] or r["pending"] == 0 or r["attempted"] == 0:
                    return 2 if r["blocked"] else 0
        elif a.cmd == "metadata":
            r = core.fetch_metadata(store, a.channel, max_videos=a.max, title_filter=a.title,
                                    refresh_list=a.refresh_list, tab=a.tab, progress=_progress)
            _print(r)
            return 2 if r["blocked"] else 0
        elif a.cmd == "channels":
            _print(store.channels())
        elif a.cmd == "find":
            _print(core.find_videos(store, a.channel, title=a.title, description=a.description, text=a.text,
                                    date_from=a.date_from, date_to=a.date_to, min_minutes=a.min_minutes,
                                    max_minutes=a.max_minutes, has_transcript=True if a.with_transcript else None,
                                    language=a.language,
                                    sort=a.sort, limit=a.limit))
        elif a.cmd == "get":
            r = core.get_transcript(store, a.video, format=a.format, clean=not a.raw, max_chars=0, languages=langs)
            if "transcript" not in r:
                _print(r)
                return 1
            print(f"# {r['title'] or r['id']}\n{r['url']}\n")
            print(r["transcript"])
        elif a.cmd == "info":
            _print(core.get_video_info(store, a.video))
        elif a.cmd == "search":
            _print(core.search(store, a.query, channel=a.channel, title=a.title, description=a.description,
                               max_results=a.max))
        elif a.cmd == "export":
            _print(core.export(store, a.channel, a.format, Path(a.out) if a.out else None,
                               format=a.text_format, title_filter=a.title))
        elif a.cmd == "youtube":
            _print(yts.search_youtube(a.query, kind=a.kind, limit=a.limit, sort=a.sort,
                                      upload_date=a.upload_date, duration=a.duration))
        elif a.cmd == "channel-search":
            _print(yts.search_in_channel(a.channel, a.query, limit=a.limit))
        elif a.cmd == "doc":
            _print(ytdoc.export_videos(
                store, video_ids=a.ids, channel=a.channel, title=a.title, description=a.description,
                text=a.text, query=a.query, date_from=a.date_from, date_to=a.date_to, language=a.language,
                limit=a.limit, format=a.format, doc_title=a.doc_title, include_description=not a.no_description,
                max_chars_per_file=a.max_chars, out_dir=Path(a.out_dir) if a.out_dir else None,
                filename=a.name, fetch_missing_videos=a.fetch_missing, fetch_limit=a.fetch_limit))
        elif a.cmd == "topic":
            _print(yttopic.find_topic_candidates(store, a.channel, a.terms, max_per_term=a.max_per_term,
                                                 use_youtube_search=not a.no_youtube))
        elif a.cmd == "catalog":
            r = ytcat.catalog(store, a.channel, offset=a.offset, limit=a.limit, description_chars=a.chars,
                              refresh=a.refresh)
            print(f"# {r['channel']}: {r['total']} videos ({r['with_metadata']} con descripcion); "
                  f"offset {r['offset']}, siguiente {r['next_offset']}")
            print("\n".join(r["videos"]))
        elif a.cmd == "select":
            if a.add or a.remove or a.channel or a.topic:
                _print(ytcat.selection_update(store, a.name, add=a.add, remove=a.remove, channel=a.channel,
                                              topic=a.topic))
            else:
                _print(ytcat.selection_show(store, a.name) if a.name else ytcat.selection_list(store))
        elif a.cmd == "process":
            r = ytcat.process_selection(store, a.name, format=a.format, fetch_limit=a.fetch_limit,
                                        max_tokens_per_file=a.max_tokens)
            _print(r)
            return 2 if (r.get("fetched") or {}).get("blocked") else 0
        elif a.cmd == "pacing":
            if a.reset:
                ytpace.get_pacer().reset()
            _print(ytpace.get_pacer().status())
        elif a.cmd == "reindex":
            _print(core.rebuild_index(store))
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except core.BlockedError as exc:
        print(f"YouTube limito esta IP: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
