"""Revision completa de un canal por el modelo: catalogo paginado (titulo + descripcion
de TODOS los videos), lista de seleccion persistente y procesamiento final.

Flujo: fetch_metadata (todo el canal) -> catalog (paginas) -> el modelo juzga cada video
segun el tema -> selection_update (va anotando los elegidos) -> process_selection (baja
solo esas transcripciones y genera un unico PDF/MD).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from . import core
from . import document as ytdoc


# ---------------------------------------------------------------------------
# Catalogo
# ---------------------------------------------------------------------------

def _clip(text: str, n: int) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


_URL_ONLY = re.compile(r"^\W*(https?://\S+|www\.\S+)\W*$", re.I)


def _norm_line(line: str) -> str:
    return re.sub(r"\s+", " ", core.fold(line)).strip()


def boilerplate_lines(store: core.Store, cid: str, min_share: float = 0.3) -> set[str]:
    """Lineas de descripcion que el canal repite en muchos videos (suscribete, redes,
    patrocinios fijos...). Se quitan del catalogo para ahorrar tokens y dejar ver lo propio
    de cada video."""
    counts: dict[str, int] = {}
    n = 0
    meta_dir = store.root / cid / "meta"
    if not meta_dir.exists():
        return set()
    for p in meta_dir.glob("*.json"):
        desc = (core._read_json(p, {}) or {}).get("description") or ""
        n += 1
        for line in {_norm_line(x) for x in desc.splitlines() if x.strip()}:
            counts[line] = counts.get(line, 0) + 1
    if n < 3:
        return set()
    return {line for line, c in counts.items() if c >= max(3, min_share * n)}


def clean_description(desc: str, boiler: set[str]) -> str:
    keep = [x.strip() for x in (desc or "").splitlines()
            if x.strip() and _norm_line(x) not in boiler and not _URL_ONLY.match(x.strip())]
    return " ".join(keep)


def catalog(store: core.Store, channel: str, *, offset: int = 0, limit: int = 100,
            description_chars: int = 400, refresh: bool = False, tab: str = core.ALL_UPLOADS,
            lister: core.Lister = core.ytdlp_lister) -> dict[str, Any]:
    """Pagina compacta del catalogo del canal: una linea por video
    'ID | fecha | duracion | titulo | descripcion'. Incluye TODOS los videos listados, tengan
    o no metadatos (los que no, dicen '(sin descripcion todavia)')."""
    try:
        cid = store.resolve(channel)
        if refresh:
            raise KeyError
    except KeyError:
        cid, _, _, _ = core._refresh_listing(store, channel, tab, None, lister)
    cmeta = store.channel_meta(cid)
    vids = store.videos(cid)
    page = vids[offset: offset + max(1, limit)]
    boiler = boilerplate_lines(store, cid)
    lines = []
    for v in page:
        meta = core._read_json(store.meta_path(cid, v["id"]), None) or {}
        dur = v.get("duration")
        desc = (_clip(clean_description(meta.get("description", ""), boiler), description_chars)
                if meta else "(sin descripcion todavia)")
        lines.append(f"{v['id']} | {v.get('date') or '?'} | {core.fmt_ts(dur) if dur else '?'} | "
                     f"{v.get('title') or '?'} | {desc or '(descripcion vacia)'}")
    with_meta = sum(1 for v in vids if v.get("has_metadata"))
    nxt = offset + len(page)
    return {
        "channel_id": cid, "channel": cmeta.get("channel"), "total": len(vids),
        "with_metadata": with_meta, "without_metadata": len(vids) - with_meta,
        "listing_complete": bool(cmeta.get("listing_complete")),
        "offset": offset, "next_offset": nxt if nxt < len(vids) else None,
        "format": "ID | fecha | duracion | titulo | descripcion",
        "videos": lines,
    }


# ---------------------------------------------------------------------------
# Lista de seleccion persistente
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", core.fold(name)).strip("-")
    if not s:
        raise ValueError("nombre de seleccion vacio")
    return s[:60]


def _path(store: core.Store, name: str):
    return store.root / "selections" / f"{_slug(name)}.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_selection(store: core.Store, name: str) -> dict[str, Any]:
    sel = core._read_json(_path(store, name), None)
    if sel is None:
        raise KeyError(f"No existe la seleccion {name!r}. Creala con selection_update.")
    return sel


def selection_update(store: core.Store, name: str, *, add: list[str] | None = None,
                     remove: list[str] | None = None, channel: str | None = None,
                     topic: str | None = None, reviewed_until: int | None = None) -> dict[str, Any]:
    """Crea o actualiza una lista: agrega/quita IDs (o URLs), guarda el tema, el canal y hasta
    que posicion del catalogo ya se reviso (para retomar si la revision se interrumpe)."""
    p = _path(store, name)
    sel = core._read_json(p, None) or {"name": name, "video_ids": [], "created_at": _now()}
    if channel:
        sel["channel"] = channel
        try:
            sel["channel_id"] = store.resolve(channel)
        except KeyError:
            pass
    if topic:
        sel["topic"] = topic
    ids = sel["video_ids"]
    added = 0
    for v in add or []:
        vid = core.video_id(v)
        if vid not in ids:
            ids.append(vid)
            added += 1
    rm = {core.video_id(v) for v in remove or []}
    before = len(ids)
    sel["video_ids"] = [i for i in ids if i not in rm]
    if reviewed_until is not None:
        sel["reviewed_until"] = max(int(reviewed_until), int(sel.get("reviewed_until") or 0))
    sel["updated_at"] = _now()
    core._write_json(p, sel)
    return {"name": sel["name"], "topic": sel.get("topic"), "channel": sel.get("channel"),
            "added": added, "removed": before - len(sel["video_ids"]), "total": len(sel["video_ids"]),
            "reviewed_until": sel.get("reviewed_until")}


def selection_show(store: core.Store, name: str) -> dict[str, Any]:
    """Contenido de la lista con titulo y estado de cada video."""
    sel = load_selection(store, name)
    rows: dict[str, dict[str, Any]] = {}
    for d in store.channel_dirs():
        for v in store.videos(d.name):
            if v["id"] in sel["video_ids"]:
                rows[v["id"]] = v
    items = []
    for vid in sel["video_ids"]:
        v = rows.get(vid, {})
        items.append(f"{vid} | {v.get('status') or 'desconocido'} | {v.get('title') or '?'}")
    st = [rows.get(i, {}).get("status") for i in sel["video_ids"]]
    return {"name": sel["name"], "topic": sel.get("topic"), "channel": sel.get("channel"),
            "total": len(sel["video_ids"]), "with_transcript": st.count(core.ST_OK),
            "reviewed_until": sel.get("reviewed_until"), "last_export": sel.get("last_export"),
            "format": "ID | estado | titulo", "videos": items}


def selection_list(store: core.Store) -> list[dict[str, Any]]:
    d = store.root / "selections"
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        sel = core._read_json(p, {})
        out.append({"name": sel.get("name"), "topic": sel.get("topic"), "channel": sel.get("channel"),
                    "total": len(sel.get("video_ids") or []), "updated_at": sel.get("updated_at")})
    return out


def process_selection(store: core.Store, name: str, *, format: str = "pdf", fetch_limit: int = 20,
                      doc_title: str | None = None, include_description: bool = True,
                      max_tokens_per_file: int = 100_000, net: dict[str, Any] | None = None) -> dict[str, Any]:
    """Baja las transcripciones que falten de la lista (hasta `fetch_limit`) y genera el documento
    con todos sus videos, partido en archivos de ~`max_tokens_per_file` tokens sin cortar ningun
    video (0 = un solo archivo), con apendice de los que no se pudieron incluir.
    Reanudable: si YouTube limita la IP, volver a llamarla completa lo que falte."""
    sel = load_selection(store, name)
    if not sel["video_ids"]:
        raise ValueError(f"La seleccion {name!r} esta vacia")
    title = doc_title or (f"{sel.get('channel') or 'YouTube'}: {sel['topic']}" if sel.get("topic") else sel["name"])
    r = ytdoc.export_videos(store, video_ids=sel["video_ids"], channel=sel.get("channel"), format=format,
                            doc_title=title, include_description=include_description,
                            max_chars_per_file=max(0, max_tokens_per_file) * ytdoc.CHARS_PER_TOKEN,
                            filename=f"{_slug(sel['name'])}", fetch_missing_videos=True,
                            fetch_limit=fetch_limit, net=net)
    sel["last_export"] = {"at": _now(), "files": [f["path"] for f in r.get("files", [])],
                          "videos": r.get("videos", 0), "missing": r.get("coverage", {}).get("without_transcript")}
    core._write_json(_path(store, name), sel)
    r["selection"] = sel["name"]
    if r.get("coverage", {}).get("without_transcript") and not (r.get("fetched") or {}).get("blocked"):
        r["hint"] = (r.get("hint", "") + " Vuelve a llamar process_selection mas tarde para completar; "
                     "el documento se regenera con todo lo descargado.").strip()
    return r
