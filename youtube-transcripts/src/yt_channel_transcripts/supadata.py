"""Proveedor de transcripciones Supadata (https://supadata.ai), opcional.

Supadata baja las transcripciones desde su propia infraestructura: no se hace ninguna
peticion a YouTube desde esta maquina, asi que no le afectan los bloqueos de la IP local.

Costes (docs de Supadata, nov 2026):
- mode=native (subtitulos existentes): 1 credito por video, sin importar la duracion.
- mode=generate/auto (transcripcion con IA): 2 creditos POR MINUTO. Aqui NO se usa: un
  podcast de 2 h sin subtitulos costaria 240 creditos.
- Un video sin subtitulos (HTTP 206) tambien cobra 1 credito.
- Plan gratis: 100 creditos/mes, 1 peticion/segundo.

Clave: variable SUPADATA_API_KEY o archivo `~/.yt-channel-transcripts/supadata.key`
(lo crea el usuario; nunca se imprime ni se guarda en el repo).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from . import core

API = "https://api.supadata.ai/v1/"
SOURCE = "supadata"


class SupadataError(core.BlockedError):
    """Error que debe detener la corrida (clave invalida, sin creditos)."""


def key_path() -> Path:
    return core.default_data_dir() / "supadata.key"


def api_key() -> str | None:
    k = os.environ.get("SUPADATA_API_KEY", "").strip()
    if k:
        return k
    try:
        k = key_path().read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    return k or None


def provider() -> str:
    """'supadata' si se pidio por YT_TRANSCRIPT_PROVIDER; si no, 'youtube'."""
    return (os.environ.get("YT_TRANSCRIPT_PROVIDER") or "youtube").strip().lower()


def _request(path: str, params: dict[str, Any] | None, key: str, opener=None) -> tuple[int, dict[str, Any]]:
    url = API + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, headers={"x-api-key": key, "User-Agent": "yt-channel-transcripts"})
    opener = opener or urllib.request.urlopen
    try:
        with opener(req, timeout=120) as r:
            body = r.read().decode("utf-8") or "{}"
            return r.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            body = {}
        return exc.code, body


def _segments(content: Any) -> list[dict[str, Any]]:
    segs = []
    for c in content or []:
        t = (c.get("text") or "").strip()
        if t:
            segs.append({"start": round((c.get("offset") or 0) / 1000, 2),
                         "duration": round((c.get("duration") or 0) / 1000, 2), "text": t})
    return segs


def _concrete_lang(languages: list[str]) -> str | None:
    """Primer idioma concreto pedido ('original' no es un idioma: Supadata no sabe cual es)."""
    for lang in languages:
        if lang.lower() != core.ORIGINAL:
            return core.lang_base(lang)
    return None


def fetch(vid: str, languages: list[str], *, key: str | None = None, opener=None,
          sleep: Callable[[float], None] = time.sleep, poll_seconds: float = 5.0,
          max_wait: float = 600.0) -> core.TranscriptResult:
    """Transcripcion por Supadata en modo native (1 credito)."""
    key = key or api_key()
    if not key:
        raise SupadataError("Falta la clave de Supadata (SUPADATA_API_KEY o el archivo "
                            f"{key_path()}).")
    params: dict[str, Any] = {"url": core.watch_url(vid), "mode": "native", "text": "false"}
    lang = _concrete_lang(languages)
    if lang:
        params["lang"] = lang
    for attempt in range(3):
        status, body = _request("transcript", params, key, opener)
        if status == 429 and attempt < 2:  # limite de 1 peticion/segundo del plan gratis
            sleep(2.0 * (attempt + 1))
            continue
        break
    if status == 202 and body.get("jobId"):  # video largo: trabajo asincrono
        job = body["jobId"]
        waited = 0.0
        while waited < max_wait:
            sleep(poll_seconds)
            waited += poll_seconds
            status, body = _request(f"transcript/{urllib.parse.quote(job)}", None, key, opener)
            st = (body.get("status") or "").lower()
            if status == 200 and (st in ("", "completed") and body.get("content") is not None):
                break
            if st == "failed":
                return core.TranscriptResult(core.ST_ERROR, error=f"supadata: trabajo fallido {body.get('error')}",
                                             source=SOURCE)
        else:
            return core.TranscriptResult(core.ST_ERROR, error="supadata: tiempo de espera agotado", source=SOURCE)
    if status == 200:
        segs = _segments(body.get("content"))
        if not segs:
            return core.TranscriptResult(core.ST_NONE, error="supadata: transcripcion vacia", source=SOURCE)
        return core.TranscriptResult(core.ST_OK, body.get("lang"), None, segs, source=SOURCE)
    if status == 206:
        return core.TranscriptResult(core.ST_NONE, error="supadata: el video no tiene subtitulos", source=SOURCE)
    code = body.get("error") or str(status)
    msg = (body.get("message") or "").replace(key, "***")[:160]
    if status in (401, 402, 403) or code in ("unauthorized", "upgrade-required", "forbidden"):
        raise SupadataError(f"Supadata {status} {code}: {msg} (clave invalida o sin creditos; se detiene).")
    if status == 429:
        raise SupadataError(f"Supadata 429 limit-exceeded: {msg}")
    if status == 404:
        return core.TranscriptResult(core.ST_NONE, error=f"supadata 404: {msg}", source=SOURCE)
    return core.TranscriptResult(core.ST_ERROR, error=f"supadata {status} {code}: {msg}", source=SOURCE)


def fetcher(vid: str, languages: list[str]) -> core.TranscriptResult:
    """Adaptador con la firma de core.Fetcher, con ritmo propio (1 peticion/segundo)."""
    return _paced_fetch(vid, languages)


def _paced_fetch(vid: str, languages: list[str]) -> core.TranscriptResult:
    from . import pacing
    p = pacing.get_pacer()
    try:
        p.before("supadata")
    except pacing.PausedError as exc:
        raise SupadataError(str(exc)) from exc
    return fetch(vid, languages)
