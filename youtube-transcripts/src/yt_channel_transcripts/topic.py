"""Descubrimiento por tema dentro de un canal: junta candidatos de varias vias para que
el modelo (que entiende la intencion) revise y elija que videos entran en un dump.

Vias:
- titulo y descripcion en el indice local (descripcion solo si hay metadatos),
- lo hablado en las transcripciones ya descargadas,
- el buscador propio del canal en YouTube (cubre titulos y descripciones de TODO el
  canal, aunque no se hayan bajado metadatos).
"""

from __future__ import annotations

from typing import Any

from . import core
from . import search as yts


def terms_query(terms: list[str]) -> str:
    """['inflacion', 'costo de vida', 'precio*'] -> '"inflacion" OR "costo de vida" OR precio*'."""
    parts = []
    for t in terms:
        t = t.strip().replace('"', "")
        if not t:
            continue
        if t.endswith("*") and " " not in t:
            parts.append(t)
        else:
            parts.append(f'"{t}"')
    if not parts:
        raise ValueError("terms vacio: indica al menos un termino")
    return " OR ".join(parts)


def find_topic_candidates(store: core.Store, channel: str, terms: list[str], *, max_per_term: int = 30,
                          use_youtube_search: bool = True, search_transcripts: bool = True,
                          tab: str = "videos", lister: core.Lister = core.ytdlp_lister,
                          searcher: yts.Searcher = yts.ytdlp_search) -> dict[str, Any]:
    """Lista el canal (incremental) y devuelve los videos que podrian tratar el tema, con la
    via por la que aparecio cada uno (`sources`). No descarga transcripciones."""
    if isinstance(terms, str):
        terms = [terms]
    q = terms_query(terms)
    cid, cmeta, merged, linfo = core._refresh_listing(store, channel, tab, None, lister)
    listed = {v["id"]: v for v in merged}
    cands: dict[str, dict[str, Any]] = {}

    def add(vid: str, source: str, base: dict[str, Any] | None = None) -> None:
        c = cands.setdefault(vid, {"id": vid, "sources": []})
        if source not in c["sources"]:
            c["sources"].append(source)
        for k, v in (base or {}).items():
            if v is not None:
                c.setdefault(k, v)

    for v in core.find_videos(store, cid, title=q, limit=100000)["videos"]:
        add(v["id"], "titulo")
    for v in core.find_videos(store, cid, description=q, limit=100000)["videos"]:
        add(v["id"], "descripcion")
    if search_transcripts:
        for r in core.search(store, q, channel=cid, max_results=100000, per_video=1)["results"]:
            add(core.video_id(r["video_url"]), "transcripcion")

    notes: list[str] = []
    if use_youtube_search:
        target = channel if "list=" not in core.channel_url(channel) else (cmeta.get("channel_url") or cid)
        for t in terms:
            term = t.strip().rstrip("*")
            if not term:
                continue
            try:
                res = yts.search_in_channel(target, term, limit=max_per_term, searcher=searcher)
            except core.BlockedError as exc:
                notes.append(f"Busqueda de YouTube limitada ({exc}); solo se uso el indice local.")
                break
            for r in res["results"]:
                add(r["id"], f"youtube:{term}", {"title": r.get("title"), "url": r.get("url"),
                                                  "duration_min": r.get("duration_min"),
                                                  "description": r.get("description")})

    out = []
    for vid, c in cands.items():
        row = listed.get(vid, {})
        meta = core._read_json(store.meta_path(cid, vid), None) or {}
        desc = (meta.get("description") or c.get("description") or "").strip().replace("\n", " ")
        dur = row.get("duration") or meta.get("duration")
        out.append({k: v for k, v in {
            "id": vid, "title": row.get("title") or meta.get("title") or c.get("title"),
            "url": core.watch_url(vid), "date": row.get("date"),
            "duration_min": round(dur / 60, 1) if dur else c.get("duration_min"),
            "has_transcript": row.get("status") == core.ST_OK,
            "status": row.get("status") or "fuera_del_listado",
            "sources": c["sources"],
            "description": (desc[:280] + "...") if len(desc) > 280 else (desc or None),
        }.items() if v is not None})
    out.sort(key=lambda c: (len(c["sources"]), c.get("date") or ""), reverse=True)  # mas vias, mas reciente
    # Videos fuera del listado (Shorts, directos): guardar titulo en el indice para que el
    # documento final pueda nombrarlos aunque no lleguen a descargarse.
    for c in out:
        if c["status"] == "fuera_del_listado" and not store.find_file("transcripts", c["id"]):
            store.index.upsert_video(core.LOOSE, cmeta.get("channel"), {
                "id": c["id"], "title": c.get("title"), "url": c["url"], "status": core.ST_PENDING,
                "duration": int(c["duration_min"] * 60) if c.get("duration_min") else None})
    no_meta = sum(1 for v in merged if not v.get("has_metadata"))
    return {
        "channel_id": cid, "channel": cmeta.get("channel"), "listed_videos": len(merged),
        "listing": linfo.get("listing"), "terms": terms, "query": q,
        "candidates": out, "total_candidates": len(out),
        "with_transcript": sum(1 for c in out if c["has_transcript"]),
        "videos_without_metadata": no_meta,
        "notes": notes,
        "hint": ("Revisa titulo y descripcion de cada candidato y descarta los que no traten el tema "
                 "(los que solo aparecen por una via son los mas dudosos). Luego llama export_videos("
                 "video_ids=[...], fetch_missing=true, fetch_limit=<n>, format='pdf', max_chars_per_file=0)."),
    }
