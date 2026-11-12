"""Integracion: el servidor MCP se levanta por stdio como lo haria Claude Code,
lista las herramientas y ejecuta una sobre una cache real en disco."""

from __future__ import annotations

import json
import sys

import anyio
from yt_channel_transcripts import core
from yt_channel_transcripts.core import Store, TranscriptResult

EXPECTED = {"harvest_channel", "list_channels", "list_videos", "get_transcript",
            "search_transcripts", "export_channel"}


def _seed(root):
    lister = lambda url, limit: {  # noqa: E731
        "channel_id": "UC" + "b" * 22, "channel": "Canal MCP", "handle": "@mcp",
        "channel_url": "https://www.youtube.com/@mcp",
        "videos": [{"id": "abcdefghijk", "title": "Hola MCP", "url": core.watch_url("abcdefghijk"),
                    "duration": 10, "date": "2026-02-01", "views": 1}]}
    core.harvest(Store(root), "@mcp", lister=lister, delay=0,
                 fetcher=lambda v, l: TranscriptResult(core.ST_OK, "es", True,
                                                       [{"start": 3, "duration": 1, "text": "frase clave"}]))


def test_servidor_stdio_end_to_end(tmp_path):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    _seed(tmp_path)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "yt_channel_transcripts.server"],
        env={"YT_TRANSCRIPTS_DIR": str(tmp_path), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})

    async def run():
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            res = await s.call_tool("search_transcripts", {"query": "FRASE clave"})
            return names, res

    names, res = anyio.run(run)
    assert names == EXPECTED
    payload = res.structured_content or json.loads(res.content[0].text)
    if "result" in payload and isinstance(payload["result"], dict):
        payload = payload["result"]
    assert payload["total_matches"] == 1
    assert payload["results"][0]["link"] == "https://www.youtube.com/watch?v=abcdefghijk&t=3s"
