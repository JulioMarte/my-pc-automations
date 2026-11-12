"""CLI equivalente a las herramientas MCP, para usarlo sin un cliente MCP.

    yt-transcripts harvest @canal --max 50 [--all] [--lang es,en]
    yt-transcripts channels
    yt-transcripts list @canal [--only-ok]
    yt-transcripts get <url|id> [--timestamps]
    yt-transcripts search "frase" [--channel @canal]
    yt-transcripts export @canal --format md|jsonl|csv [--out ruta]
    yt-transcripts serve            # servidor MCP por stdio
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import core


def _print(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # consola de Windows: evitar errores con acentos
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    p = argparse.ArgumentParser(prog="yt-transcripts", description="Transcripciones de canales de YouTube")
    p.add_argument("--data-dir", help="carpeta de cache (por defecto YT_TRANSCRIPTS_DIR o ~/.yt-channel-transcripts)")
    sub = p.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest", help="listar el canal y bajar transcripciones")
    h.add_argument("channel")
    h.add_argument("--max", type=int, default=25, help="transcripciones a bajar en esta corrida")
    h.add_argument("--list-limit", type=int, default=None, help="videos recientes a listar")
    h.add_argument("--all", action="store_true", help="seguir hasta terminar todo el canal")
    h.add_argument("--lang", default=None, help="idiomas preferidos, p. ej. es,en")
    h.add_argument("--tab", default="videos", choices=core.TABS)
    h.add_argument("--retry-errors", action="store_true")
    h.add_argument("--delay", type=float, default=1.0)

    sub.add_parser("channels", help="canales en cache")

    lv = sub.add_parser("list", help="videos de un canal en cache")
    lv.add_argument("channel")
    lv.add_argument("--only-ok", action="store_true")
    lv.add_argument("--limit", type=int, default=1000)

    g = sub.add_parser("get", help="transcripcion de un video")
    g.add_argument("video")
    g.add_argument("--timestamps", action="store_true")
    g.add_argument("--lang", default=None)

    s = sub.add_parser("search", help="buscar en las transcripciones")
    s.add_argument("query")
    s.add_argument("--channel")
    s.add_argument("--max", type=int, default=20)

    e = sub.add_parser("export", help="exportar titulo+enlace+transcripcion")
    e.add_argument("channel")
    e.add_argument("--format", default="jsonl", choices=("jsonl", "csv", "md"))
    e.add_argument("--out")
    e.add_argument("--timestamps", action="store_true")

    sub.add_parser("serve", help="servidor MCP por stdio")

    a = p.parse_args(argv)
    store = core.Store(Path(a.data_dir) if a.data_dir else None)
    langs = [x.strip() for x in a.lang.split(",")] if getattr(a, "lang", None) else None

    if a.cmd == "serve":
        from .server import main as serve
        serve()
        return 0
    if a.cmd == "harvest":
        def progress(i: int, n: int, title: str) -> None:
            if i < n:
                print(f"  [{i + 1}/{n}] {title}", file=sys.stderr)

        while True:
            r = core.harvest(store, a.channel, max_videos=a.max, list_limit=a.list_limit,
                             languages=langs, tab=a.tab, retry_errors=a.retry_errors,
                             delay=a.delay, progress=progress)
            _print(r)
            if not a.all or r["blocked"] or r["pending"] == 0 or r["attempted"] == 0:
                return 2 if r["blocked"] else 0
    if a.cmd == "channels":
        _print(store.channels())
    elif a.cmd == "list":
        _print(core.list_videos(store, a.channel, only_with_transcript=a.only_ok, limit=a.limit))
    elif a.cmd == "get":
        r = core.get_transcript(store, a.video, timestamps=a.timestamps, max_chars=0, languages=langs)
        if "transcript" in r:
            print(f"# {r['title'] or r['id']}\n{r['url']}\n")
            print(r["transcript"])
        else:
            _print(r)
            return 1
    elif a.cmd == "search":
        _print(core.search(store, a.query, channel=a.channel, max_results=a.max))
    elif a.cmd == "export":
        _print(core.export(store, a.channel, a.format, Path(a.out) if a.out else None, a.timestamps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
