"""Integracion: el servidor MCP se levanta por stdio como lo haria Claude Code,
lista herramientas/recursos/prompts y ejecuta filtros sobre una cache real en disco."""

from __future__ import annotations

import json
import os
import sys

import anyio

from yt_channel_transcripts import core
from yt_channel_transcripts.core import Store, TranscriptResult

EXPECTED = {"search_youtube", "search_channel_videos", "harvest_channel", "fetch_metadata", "list_channels", "find_videos", "search_transcripts",
            "get_transcript", "get_video_info", "export_channel", "export_videos", "rebuild_index"}


def _seed(root):
    vids = {"abcdefghijk": ("Hola MCP", "Video sobre protocolos"), "bbbbbbbbbbb": ("Otro tema", "Cocina facil")}
    lister = lambda url, limit, known=None: {  # noqa: E731
        "channel_id": "UC" + "b" * 22, "channel": "Canal MCP", "handle": "@mcp", "exhausted": True,
        "channel_url": "https://www.youtube.com/@mcp",
        "videos": [{"id": k, "title": t, "url": core.watch_url(k), "duration": 10, "date": "2026-02-01",
                    "views": 1} for k, (t, _) in vids.items()]}
    st = Store(root)
    core.harvest(st, "@mcp", lister=lister, delay=0,
                 enricher=lambda v: {"id": v, "title": vids[v][0], "description": vids[v][1], "upload_date": "20260201"},
                 fetcher=lambda v, l: TranscriptResult(core.ST_OK, "es", True,
                                                       [{"start": 3, "duration": 1, "text": f"frase clave {v}"}]))
    st.close()


def _payload(res):
    data = res.structured_content or json.loads(res.content[0].text)
    return data["result"] if isinstance(data, dict) and isinstance(data.get("result"), (dict, list)) else data


def test_servidor_stdio_end_to_end(tmp_path):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    _seed(tmp_path)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "yt_channel_transcripts.server"],
        env={"YT_TRANSCRIPTS_DIR": str(tmp_path), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")})

    async def run():
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            prompts = {p.name for p in (await s.list_prompts()).prompts}
            templates = {t.uri_template for t in (await s.list_resource_templates()).resource_templates}
            found = await s.call_tool("find_videos", {"description": "protocolos"})
            by_title = await s.call_tool("find_videos", {"title": "otro"})
            hits = await s.call_tool("search_transcripts", {"query": "FRASE clave", "title": "hola"})
            res = await s.read_resource("yt://video/abcdefghijk")
            doc = await s.call_tool("export_videos", {"query": "frase clave", "format": "both",
                                                      "return_content": True})
            name = _payload(doc)["files"][0]["path"].replace("\\", "/").rsplit("/", 1)[1]
            via_res = await s.read_resource(f"yt://exports/{name}")
            return names, prompts, templates, found, by_title, hits, res, doc, via_res

    names, prompts, templates, found, by_title, hits, res, doc, via_res = anyio.run(run)
    assert names == EXPECTED
    assert prompts == {"investigar_tema", "resumir_video"}
    assert "yt://video/{video_id}" in templates
    f = _payload(found)
    assert [v["id"] for v in f["videos"]] == ["abcdefghijk"] and f["videos"][0]["description"] == "Video sobre protocolos"
    assert [v["title"] for v in _payload(by_title)["videos"]] == ["Otro tema"]
    h = _payload(hits)
    assert h["videos_matched"] == 1
    assert h["results"][0]["link"] == "https://www.youtube.com/watch?v=abcdefghijk&t=3s"
    md = res.contents[0].text
    assert md.startswith("# Hola MCP") and "Video sobre protocolos" in md and "[0:03] frase clave" in md
    d = _payload(doc)
    assert d["videos"] == 2 and [f["format"] for f in d["files"]] == ["md", "pdf"]
    assert d["content"].startswith("# Canal MCP: 2 videos") and via_res.contents[0].text == d["content"]
