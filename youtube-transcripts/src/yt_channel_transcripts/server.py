"""Servidor MCP (stdio) sobre la logica de `core`.

Flujo pensado para un modelo: harvest_channel (descarga a disco, devuelve solo
un resumen) -> list_videos / search_transcripts -> get_transcript (paginado).
Asi las transcripciones no inundan el contexto salvo cuando se piden.
"""

from __future__ import annotations

from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer

from . import core

INSTRUCTIONS = """\
Herramientas para procesar transcripciones de videos de canales de YouTube.
1. harvest_channel: lista los videos del canal y descarga transcripciones a una cache local
   (incremental; si 'pending' > 0, vuelve a llamarla para continuar).
2. list_videos: titulo, enlace, fecha y estado de cada video.
3. search_transcripts: busca una frase en todas las transcripciones; devuelve enlaces al segundo exacto.
4. get_transcript: texto completo de un video (paginado con offset/next_offset).
5. export_channel: escribe titulo+enlace+transcripcion de todo el canal a jsonl/csv/md y devuelve la ruta.
Si 'blocked' viene con texto, YouTube limito la IP: espera antes de seguir."""

mcp = MCPServer("youtube-transcripts", instructions=INSTRUCTIONS)


def _store() -> core.Store:
    return core.Store()


@mcp.tool()
async def harvest_channel(
    channel: str,
    max_videos: int = 25,
    list_limit: int | None = None,
    languages: list[str] | None = None,
    tab: str = "videos",
    retry_errors: bool = False,
    delay_seconds: float = 1.0,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Descarga transcripciones de un canal a la cache local y devuelve un resumen.

    channel: @handle, URL del canal, ID 'UC...' o URL de playlist.
    max_videos: cuantas transcripciones pendientes bajar en esta llamada (las mas recientes primero).
    list_limit: cuantos videos recientes listar del canal (None = el canal completo).
    languages: preferencia de idioma, p. ej. ["es","en"]; manual antes que automatica.
    tab: videos | streams | shorts.
    retry_errors: reintentar videos que fallaron por errores transitorios.
    """
    def progress(i: int, n: int, title: str) -> None:
        if ctx is not None and n:
            try:
                anyio.from_thread.run(ctx.report_progress, i, n, title)
            except Exception:
                pass

    return await anyio.to_thread.run_sync(lambda: core.harvest(
        _store(), channel, max_videos=max_videos, list_limit=list_limit, languages=languages,
        tab=tab, retry_errors=retry_errors, delay=delay_seconds, progress=progress))


@mcp.tool()
def list_channels() -> list[dict[str, Any]]:
    """Canales ya descargados, con cuantos videos y transcripciones hay en cache."""
    return _store().channels()


@mcp.tool()
def list_videos(channel: str, only_with_transcript: bool = False, limit: int = 100,
                offset: int = 0) -> dict[str, Any]:
    """Videos de un canal descargado: id, titulo, enlace, fecha, estado, idioma y palabras."""
    return core.list_videos(_store(), channel, only_with_transcript=only_with_transcript,
                            limit=limit, offset=offset)


@mcp.tool()
async def get_transcript(video: str, timestamps: bool = False, max_chars: int = 20000,
                         offset: int = 0, languages: list[str] | None = None) -> dict[str, Any]:
    """Transcripcion de un video (ID o URL). Si no esta en cache la descarga.
    Paginada: si next_offset no es null, vuelve a llamar con offset=next_offset."""
    return await anyio.to_thread.run_sync(lambda: core.get_transcript(
        _store(), video, timestamps=timestamps, max_chars=max_chars, offset=offset,
        languages=languages))


@mcp.tool()
def search_transcripts(query: str, channel: str | None = None, max_results: int = 20,
                       context_chars: int = 160) -> dict[str, Any]:
    """Busca una frase (sin importar tildes/mayusculas) en las transcripciones guardadas.
    Devuelve titulo, enlace al segundo exacto y fragmento de contexto."""
    return core.search(_store(), query, channel=channel, max_results=max_results,
                       context_chars=context_chars)


@mcp.tool()
def export_channel(channel: str, format: str = "jsonl", timestamps: bool = False) -> dict[str, Any]:
    """Exporta titulo, enlace, fecha, idioma y transcripcion de cada video a un archivo
    (jsonl, csv o md) dentro de la cache y devuelve la ruta."""
    return core.export(_store(), channel, format, timestamps=timestamps)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
