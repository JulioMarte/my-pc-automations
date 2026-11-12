"""YouTube Data API v3 (oficial) para LISTADO y METADATOS, si el usuario configura YT_API_KEY.

Es la via correcta para titulos y descripciones: 1 unidad de cuota por cada 50 videos
(playlistItems.list y videos.list), de 10 000 unidades/dia gratis. Un canal de 400 videos
cuesta ~18 unidades y ~18 peticiones, frente a >1000 paginas web sin la API.

No sirve para transcripciones de videos ajenos: captions.download exige permiso de edicion
sobre el video. Las transcripciones siguen por las vias publicas (con ritmo de pacing.py).

La clave nunca se escribe en logs ni en mensajes de error.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

API = "https://www.googleapis.com/youtube/v3/"


class OfficialAPIError(RuntimeError):
    pass


def api_key() -> str | None:
    k = os.environ.get("YT_API_KEY", "").strip()
    return k or None


def _get(endpoint: str, params: dict[str, Any], key: str, opener=None) -> dict[str, Any]:
    url = API + endpoint + "?" + urllib.parse.urlencode({**params, "key": key})
    opener = opener or urllib.request.urlopen  # resuelto al llamar (los tests lo sustituyen)
    try:
        with opener(url, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode("utf-8")).get("error", {})
            reason = (err.get("errors") or [{}])[0].get("reason") or err.get("status") or ""
            msg = err.get("message", "")
        except Exception:
            reason, msg = "", ""
        msg = msg.replace(key, "***")
        raise OfficialAPIError(f"YouTube Data API {exc.code} {reason}: {msg[:200]}") from None
    except urllib.error.URLError as exc:
        raise OfficialAPIError(f"YouTube Data API sin conexion: {exc.reason}") from None


def iso_duration(s: str | None) -> int | None:
    """'PT1H2M3S' -> 3723."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


_CHAP = re.compile(r"^\s*\(?((?:\d{1,2}:)?\d{1,2}:\d{2})\)?\s*[-–—:|]?\s*(.+?)\s*$")


def chapters_from_description(desc: str) -> list[dict[str, Any]]:
    """Capitulos segun la regla de YouTube: lineas con marca de tiempo, la primera en 0:00 y
    al menos 3."""
    out = []
    for line in (desc or "").splitlines():
        m = _CHAP.match(line)
        if m:
            secs = 0
            for part in m.group(1).split(":"):
                secs = secs * 60 + int(part)
            out.append({"start_time": float(secs), "title": m.group(2)})
    if len(out) < 3 or out[0]["start_time"] != 0:
        return []
    out.sort(key=lambda c: c["start_time"])
    for a, b in zip(out, out[1:]):
        a["end_time"] = b["start_time"]
    return out


def uploads_playlist(channel_id: str) -> str:
    return "UU" + channel_id[2:]


def channel_lookup(handle_or_id: str, key: str, opener=None) -> dict[str, Any]:
    """{'channel_id', 'channel', 'handle'} a partir de @handle o ID 'UC...' (1 unidad)."""
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", handle_or_id):
        params = {"part": "snippet", "id": handle_or_id}
    else:
        h = handle_or_id if handle_or_id.startswith("@") else "@" + handle_or_id
        params = {"part": "snippet", "forHandle": h}
    items = _get("channels", params, key, opener).get("items") or []
    if not items:
        raise OfficialAPIError(f"No existe el canal {handle_or_id}")
    sn = items[0].get("snippet") or {}
    return {"channel_id": items[0]["id"], "channel": sn.get("title"), "handle": sn.get("customUrl")}


def list_uploads(channel_id: str, key: str, limit: int | None = None, known: set[str] | None = None,
                 opener=None) -> dict[str, Any]:
    """Subidas del canal (mas reciente primero), 50 por peticion. Con `known` corta tras 10
    conocidos seguidos, igual que el listado incremental. Devuelve {'videos', 'exhausted'}."""
    out: list[dict[str, Any]] = []
    token = None
    streak = 0
    while True:
        p = {"part": "snippet,contentDetails", "playlistId": uploads_playlist(channel_id), "maxResults": 50}
        if token:
            p["pageToken"] = token
        r = _get("playlistItems", p, key, opener)
        for it in r.get("items") or []:
            vid = it["contentDetails"]["videoId"]
            sn = it.get("snippet") or {}
            out.append({"id": vid, "title": sn.get("title") or "", "url": f"https://www.youtube.com/watch?v={vid}",
                        "duration": None, "date": (it["contentDetails"].get("videoPublishedAt") or "")[:10] or None,
                        "views": None})
            if known is not None:
                streak = streak + 1 if vid in known else 0
                if streak >= 10:
                    return {"videos": out, "exhausted": False}
            if limit and len(out) >= limit:
                return {"videos": out, "exhausted": False}
        token = r.get("nextPageToken")
        if not token:
            return {"videos": out, "exhausted": True}


def videos_info(ids: Iterable[str], key: str, opener=None) -> dict[str, dict[str, Any]]:
    """Metadatos de hasta 50 videos por peticion, con la forma que espera core.metadata_from_info."""
    ids = list(ids)
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i: i + 50]
        r = _get("videos", {"part": "snippet,contentDetails,statistics", "id": ",".join(chunk),
                            "maxResults": 50}, key, opener)
        for it in r.get("items") or []:
            sn, cd, stt = it.get("snippet") or {}, it.get("contentDetails") or {}, it.get("statistics") or {}
            desc = sn.get("description") or ""
            out[it["id"]] = {
                "id": it["id"], "title": sn.get("title"), "description": desc, "tags": sn.get("tags") or [],
                "upload_date": (sn.get("publishedAt") or "")[:10].replace("-", "") or None,
                "duration": iso_duration(cd.get("duration")),
                "view_count": int(stt["viewCount"]) if stt.get("viewCount") else None,
                "like_count": int(stt["likeCount"]) if stt.get("likeCount") else None,
                "language": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage"),
                "channel": sn.get("channelTitle"), "channel_id": sn.get("channelId"),
                "chapters": chapters_from_description(desc),
            }
    return out
