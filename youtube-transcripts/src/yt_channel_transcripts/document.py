"""Documentos para LLM: junta varios videos (titulo, metadatos, descripcion, capitulos
y transcripcion en parrafos con minuto) en un Markdown y/o PDF listos para entregar a
otro modelo o para que el mismo modelo los analice.

Markdown es el formato recomendado para un LLM (menos tokens, estructura explicita).
El PDF sirve para subirlo a interfaces de chat o para lectura humana; usa fuentes del
sistema (Arial/DejaVu) para que se vean bien las tildes.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from . import core
from . import text as T

CHARS_PER_TOKEN = 4  # aproximacion habitual para estimar tokens
DEFAULT_MAX_CHARS = 400_000  # ~100k tokens por archivo Markdown; 0 = un solo archivo


# ---------------------------------------------------------------------------
# Seleccion de videos
# ---------------------------------------------------------------------------

def collect(store: core.Store, *, video_ids: list[str] | None = None, channel: str | None = None,
            title: str | None = None, description: str | None = None, text: str | None = None,
            query: str | None = None, date_from: str | None = None, date_to: str | None = None,
            language: str | None = None, limit: int | None = None) -> dict[str, Any]:
    """Elige TODOS los videos con transcripcion que cumplen IDs y/o filtros (o los primeros
    `limit`). Con `query` (busqueda en lo hablado) se ordenan por relevancia y se anotan los
    minutos donde aparece. Devuelve tambien la cobertura: cuantos cumplen el filtro pero no
    tienen transcripcion y cuantos no se pudieron evaluar por falta de metadatos."""
    ids = [core.video_id(v) for v in video_ids] if video_ids else None
    # Con IDs explicitos el canal no filtra: un directo encontrado por busqueda puede no estar
    # en el listado del canal y se guarda como video suelto.
    filters = dict(channel=None if ids else channel, title=title, description=description, text=text,
                   date_from=date_from, date_to=date_to)
    if not ids and not query and not any(filters.values()):
        raise ValueError("Indica video_ids o algun filtro (channel, title, description, text, query, fechas).")

    hits: dict[str, list[dict[str, Any]]] = {}
    order: list[str] | None = ids
    if query:
        sr = core.search(store, query, max_results=5000, per_video=5, video_ids=ids,
                         **{k: v for k, v in filters.items() if v})
        for r in sr["results"]:
            vid = core.video_id(r["video_url"])
            hits.setdefault(vid, []).append(r)
        order = list(hits) if ids is None else [i for i in ids if i in hits]
        if not order:  # la busqueda no encontro nada: no caer a "todos los videos"
            return {"records": [], "without_transcript": [], "truncated": False,
                    "coverage": {"matching": 0, "with_transcript": 0, "without_transcript": 0,
                                 "note": "query solo busca en transcripciones ya descargadas"}}

    found = core.find_videos(store, video_ids=order, has_transcript=True, limit=100000,
                             **{k: v for k, v in filters.items() if v})
    ok_ids = {v["id"] for v in found["videos"]}
    if order is None:
        order = [v["id"] for v in found["videos"]]  # mas reciente primero
    matched = [i for i in order if i in ok_ids]
    selected = matched[: max(1, limit)] if limit else matched

    missing: list[str] = []
    if ids:
        missing = [i for i in ids if i not in ok_ids]
    elif not query:
        nt = core.find_videos(store, has_transcript=False, limit=100000, **{k: v for k, v in filters.items() if v})
        missing = [v["id"] for v in nt["videos"]]
    coverage: dict[str, Any] = {"matching": len(matched) + len(missing), "with_transcript": len(matched),
                                "without_transcript": len(missing)}
    if (description or text) and not ids:
        scope = {k: v for k, v in dict(channel=channel, date_from=date_from, date_to=date_to).items() if v}
        allv = core.find_videos(store, limit=100000, **scope)["videos"]
        n = sum(1 for v in allv if not v.get("has_metadata"))
        if n:
            coverage["not_evaluated_no_metadata"] = n
            coverage["note"] = (f"{n} videos no tienen metadatos y no se pudo evaluar su descripcion; "
                                "usa fetch_metadata o fetch_missing.")
    if query:
        coverage["note"] = "query solo busca en transcripciones ya descargadas"

    records = []
    for vid in selected:
        rec = _record(store, vid, language)
        if rec:
            rec["hits"] = sorted(hits.get(vid, []), key=lambda h: _secs(h["at"]))
            records.append(rec)
    return {"records": records, "without_transcript": missing,
            "truncated": len(matched) > len(selected), "coverage": coverage}


def _channel_of(store: core.Store, vid: str) -> str | None:
    for d in store.channel_dirs():
        if any(v["id"] == vid for v in store.videos(d.name)):
            return d.name
    return None


def fetch_missing(store: core.Store, *, video_ids: list[str] | None, channel: str | None, title: str | None,
                  description: str | None, text: str | None, date_from: str | None, date_to: str | None,
                  fetch_limit: int, describe_first: bool, net: dict[str, Any]) -> dict[str, Any]:
    """Descarga (metadatos + transcripcion) los videos que cumplen el filtro y aun no tienen
    transcripcion, hasta `fetch_limit`. Si se filtra por descripcion, primero baja los
    metadatos que falten del canal para poder evaluar ese filtro."""
    summary: dict[str, Any] = {"attempted": 0, "downloaded": 0, "without_transcript": 0, "errors": 0,
                               "metadata_fetched": 0, "blocked": None}
    meta_net = {k: v for k, v in net.items() if k in ("lister", "enricher", "delay", "sleep")}
    if describe_first and channel and (description or text) and not video_ids:
        m = core.fetch_metadata(store, channel, max_videos=fetch_limit * 4, **meta_net)
        summary["metadata_fetched"] = m["fetched"]
        if m["blocked"]:
            summary["blocked"] = m["blocked"]
            return summary
    pre = collect(store, video_ids=video_ids, channel=channel, title=title, description=description,
                  text=text, date_from=date_from, date_to=date_to)
    missing = pre["without_transcript"][: max(0, fetch_limit)]
    if not missing:
        return summary
    groups: dict[str | None, list[str]] = {}
    if channel:
        try:
            listed = {v["id"] for v in store.videos(store.resolve(channel))}
        except KeyError:
            listed = set()
        inside = [v for v in missing if v in listed]
        outside = [v for v in missing if v not in listed]  # p. ej. directos encontrados por busqueda
        if inside:
            groups[channel] = inside
        if outside:
            groups[None] = outside
    else:
        for vid in missing:
            groups.setdefault(_channel_of(store, vid), []).append(vid)
    harvest_net = {k: v for k, v in net.items() if k in ("lister", "fetcher", "enricher", "sub_fetcher", "delay", "sleep")}
    for ch, vids in groups.items():
        if ch is None:  # videos sueltos: sin canal conocido
            for vid in vids:
                summary["attempted"] += 1
                try:
                    r = core.get_transcript(store, vid, max_chars=1, **{k: v for k, v in net.items()
                                                                         if k in ("fetcher", "enricher", "sub_fetcher")})
                except core.BlockedError as exc:
                    summary["attempted"] -= 1
                    summary["blocked"] = str(exc) or "bloqueado"
                    return summary
                key = "downloaded" if "transcript" in r else ("without_transcript" if r.get("status") == core.ST_NONE
                                                               else "errors")
                summary[key] += 1
            continue
        r = core.harvest(store, ch, video_ids=vids, max_videos=len(vids), retry_errors=True, **harvest_net)
        for k in ("attempted", "downloaded", "without_transcript", "errors", "metadata_fetched"):
            summary[k] += r.get(k, 0)
        if r.get("blocked"):
            summary["blocked"] = r["blocked"]
            break
    return summary


_REASONS = {
    core.ST_NONE: "el video no tiene subtitulos/transcripcion en YouTube",
    core.ST_ERROR: "fallo la descarga (se reintentara)",
    core.ST_PENDING: "pendiente de descarga (no se intento todavia o YouTube limito la IP)",
}


def missing_info(store: core.Store, ids: list[str], cap: int = 500) -> list[dict[str, Any]]:
    """Titulo, enlace y motivo de los videos seleccionados que no entraron al documento."""
    rows: dict[str, dict[str, Any]] = {}
    for d in store.channel_dirs():
        for v in store.videos(d.name):
            if v["id"] in ids:
                rows[v["id"]] = v
    unknown = [i for i in ids[:cap] if i not in rows]
    if unknown:  # p. ej. Shorts/directos encontrados por busqueda: titulo desde el indice
        for v in store.index.find_videos(video_ids=unknown, limit=len(unknown))["videos"]:
            rows[v["id"]] = {"title": v.get("title"), "status": v.get("status"), "outside": True}
    out = []
    for vid in ids[:cap]:
        v = rows.get(vid, {})
        st = v.get("status")
        reason = _REASONS.get(st, "no esta descargado")
        if v.get("outside"):
            reason = "fuera del listado principal del canal (Short o directo); " + reason
        if st == core.ST_ERROR and v.get("error"):
            reason += f": {v['error'][:80]}"
        out.append({"id": vid, "title": v.get("title") or vid, "url": core.watch_url(vid), "reason": reason})
    return out


def _missing_md(missing: list[dict[str, Any]], total: int) -> str:
    lines = ["## Videos relevantes no incluidos", "",
             f"{total} videos cumplen la seleccion pero no estan en este documento:", ""]
    lines += [f"- {m['title']} - {m['url']} - {m['reason']}" for m in missing]
    if total > len(missing):
        lines.append(f"- ... y {total - len(missing)} mas")
    return "\n".join(lines) + "\n"


def _record(store: core.Store, vid: str, language: str | None) -> dict[str, Any] | None:
    hit = store.find_file("transcripts", vid)
    if not hit:
        return None
    cid, doc = hit
    if language and core.lang_base(doc.get("language")) != core.lang_base(language):
        var = store.load_variant(vid, core.lang_base(language) or language)
        if var:
            doc = var
    meta = store.load_meta(vid) or {}
    cmeta = store.channel_meta(cid) if cid != core.LOOSE else {}
    row = next((v for v in store.videos(cid) if v["id"] == vid), {}) if cid != core.LOOSE else {}
    return {
        "id": vid, "title": doc.get("title") or meta.get("title") or row.get("title") or vid,
        "url": core.watch_url(vid), "channel": meta.get("channel") or cmeta.get("channel"),
        "handle": cmeta.get("handle"), "date": meta.get("date") or row.get("date") or doc.get("date"),
        "date_exact": bool(meta.get("date")), "duration": meta.get("duration") or row.get("duration"),
        "language": doc.get("language"), "is_generated": doc.get("is_generated"),
        "description": (meta.get("description") or "").strip(), "chapters": meta.get("chapters") or [],
        "segments": doc.get("segments") or [],
    }


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def _secs(ts: str) -> int:
    n = 0
    for part in ts.split(":"):
        n = n * 60 + int(part)
    return n


def _dur(seconds: Any) -> str:
    return T.fmt_ts(float(seconds)) if seconds else "?"


def _lang(rec: dict[str, Any]) -> str:
    if not rec.get("language"):
        return "?"
    kind = {True: "automática", False: "manual"}.get(rec.get("is_generated"), "")
    return f"{rec['language']} ({kind})" if kind else rec["language"]


def _video_md(n: int, rec: dict[str, Any], *, include_description: bool, include_chapters: bool,
              query: str | None) -> str:
    ch = rec.get("channel") or "?"
    if rec.get("handle"):
        ch += f" ({rec['handle']})"
    date = rec.get("date") or "?"
    if rec.get("date") and not rec.get("date_exact"):
        date += " (aprox.)"
    out = [f"## {n}. {rec['title']}", "",
           f"- **Canal:** {ch} | **Fecha:** {date} | **Duración:** {_dur(rec.get('duration'))} | "
           f"**Idioma:** {_lang(rec)}",
           f"- **Enlace:** {rec['url']}"]
    if query and rec.get("hits"):
        marks = ", ".join(f"[{h['at']}]" for h in rec["hits"])
        out.append(f"- **Dónde aparece la búsqueda `{query}`:** {marks}")
    if include_description and rec.get("description"):
        out += ["", "### Descripción", "", rec["description"]]
    if include_chapters and rec.get("chapters"):
        out += ["", "### Capítulos", ""]
        out += [f"- [{T.fmt_ts(float(c.get('start_time') or 0))}] {c.get('title')}" for c in rec["chapters"]]
    out += ["", "### Transcripción", ""]
    last = None
    for p in T.paragraphs(rec["segments"], rec.get("chapters")):
        if include_chapters and p["chapter"] and p["chapter"] != last:
            out += [f"#### {p['chapter']}", ""]
            last = p["chapter"]
        out += [f"[{T.fmt_ts(p['start'])}] {p['text']}", ""]
    return "\n".join(out).rstrip() + "\n"


def _header_md(doc_title: str, records: list[dict[str, Any]], criteria: str, part: str = "") -> str:
    langs = sorted({r["language"] for r in records if r.get("language")})
    lines = [f"# {doc_title}{part}", "",
             f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')} con youtube-transcripts. "
             f"{len(records)} videos. Idiomas: {', '.join(langs) or '?'}.",
             f"Selección: {criteria}", "",
             "Cómo leer este documento: cada video empieza con `## N.`; cada párrafo de la "
             "transcripción empieza con `[m:ss]`, el minuto del video. Para enlazar un minuto, usa el "
             "enlace del video y agrega `&t=<segundos>s`. Las transcripciones automáticas pueden tener "
             "errores de reconocimiento y puntuación poco fiable.", "",
             "## Índice", ""]
    for i, r in enumerate(records, 1):
        lines.append(f"{i}. {r['title']} ({r.get('channel') or '?'}, {r.get('date') or '?'}, "
                     f"{_dur(r.get('duration'))})")
    return "\n".join(lines) + "\n"


def render_markdown(records: list[dict[str, Any]], *, doc_title: str, criteria: str,
                    include_description: bool = True, include_chapters: bool = True,
                    query: str | None = None, max_chars_per_file: int = 0,
                    missing: list[dict[str, Any]] | None = None, missing_total: int = 0) -> list[str]:
    """Devuelve uno o varios documentos Markdown. Con `max_chars_per_file` > 0 se parte
    entre videos (un video nunca se corta; si uno solo supera el limite va solo)."""
    bodies = [_video_md(i, r, include_description=include_description, include_chapters=include_chapters,
                        query=query) for i, r in enumerate(records, 1)]
    tail = ("\n---\n\n" + _missing_md(missing, missing_total or len(missing))) if missing else ""
    if max_chars_per_file <= 0:
        return [_header_md(doc_title, records, criteria) + "\n---\n\n" + "\n---\n\n".join(bodies) + tail]
    groups: list[list[int]] = [[]]
    size = 0
    for i, b in enumerate(bodies):
        if groups[-1] and size + len(b) > max_chars_per_file:
            groups.append([])
            size = 0
        groups[-1].append(i)
        size += len(b)
    docs = []
    for g, idxs in enumerate(groups, 1):
        part = f" (parte {g} de {len(groups)})" if len(groups) > 1 else ""
        recs = [records[i] for i in idxs]
        head = _header_md(doc_title, recs, criteria, part)
        docs.append(head + "\n---\n\n" + "\n---\n\n".join(bodies[i] for i in idxs))
    if tail:
        docs[-1] += tail
    return docs


# ---------------------------------------------------------------------------
# PDF (fpdf2)
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/DejaVuSans.ttf", "C:/Windows/Fonts/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
]


def _find_font() -> tuple[str, str | None] | None:
    env = os.environ.get("YT_PDF_FONT")
    if env and Path(env).exists():
        bold = os.environ.get("YT_PDF_FONT_BOLD")
        return env, bold if bold and Path(bold).exists() else None
    for reg, bold in _FONT_CANDIDATES:
        if Path(reg).exists():
            return reg, bold if Path(bold).exists() else None
    return None


_ASTRAL = re.compile(r"[\U00010000-\U0010FFFF\u200d\ufe0f\ufe0e]")


def _pdf_text(s: str, unicode_font: bool) -> str:
    s = _ASTRAL.sub("", s or "")  # emojis: no estan en Arial/DejaVu
    s = "".join(ch for ch in s if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    s = re.sub(r"[ \t]{2,}", " ", s).strip(" ")
    return s if unicode_font else s.encode("latin-1", "replace").decode("latin-1")


def render_pdf(records: list[dict[str, Any]], path: Path, *, doc_title: str, criteria: str,
               include_description: bool = True, include_chapters: bool = True,
               query: str | None = None, missing: list[dict[str, Any]] | None = None,
               missing_total: int = 0) -> Path:
    from fpdf import FPDF

    logging.getLogger("fontTools").setLevel(logging.ERROR)
    logging.getLogger("fpdf").setLevel(logging.ERROR)
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.set_title(doc_title)
    pdf.set_creator("youtube-transcripts")
    font = _find_font()
    uni = font is not None
    if font:
        pdf.add_font("Doc", "", font[0])
        pdf.add_font("Doc", "B", font[1] or font[0])
        fam = "Doc"
    else:
        fam = "helvetica"
    tx = lambda s: _pdf_text(s, uni)  # noqa: E731

    def heading(text_: str, size: int, gap: float = 3) -> None:
        pdf.set_font(fam, "B", size)
        pdf.multi_cell(0, size * 0.5, tx(text_), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(gap)

    def para(text_: str, size: int = 10, h: float = 5) -> None:
        pdf.set_font(fam, "", size)
        pdf.multi_cell(0, h, tx(text_), new_x="LMARGIN", new_y="NEXT")

    pdf.add_page()
    heading(doc_title, 18, 4)
    para(f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')} con youtube-transcripts. "
         f"{len(records)} videos.")
    para(f"Selección: {criteria}")
    pdf.ln(2)
    para("Cada párrafo de la transcripción empieza con [m:ss], el minuto del video; el minuto es un "
         "enlace a ese punto. Las transcripciones automáticas pueden tener errores.", 9, 4.5)
    pdf.ln(4)
    heading("Índice", 13)
    for i, r in enumerate(records, 1):
        para(f"{i}. {r['title']} ({r.get('channel') or '?'}, {r.get('date') or '?'}, {_dur(r.get('duration'))})", 10)

    for i, r in enumerate(records, 1):
        pdf.add_page()
        pdf.start_section(tx(f"{i}. {r['title']}")[:120])
        heading(f"{i}. {r['title']}", 14)
        ch = (r.get("channel") or "?") + (f" ({r['handle']})" if r.get("handle") else "")
        fecha = (r.get("date") or "?") + (" (aprox.)" if r.get("date") and not r.get("date_exact") else "")
        para(f"Canal: {ch}   Fecha: {fecha}   Duración: {_dur(r.get('duration'))}   "
             f"Idioma: {_lang(r)}", 9, 4.5)
        pdf.set_font(fam, "", 9)
        pdf.set_text_color(20, 60, 160)
        pdf.cell(0, 5, r["url"], link=r["url"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        if query and r.get("hits"):
            para(f"Dónde aparece la búsqueda «{query}»: " + ", ".join(f"[{h['at']}]" for h in r["hits"]), 9, 4.5)
        if include_description and r.get("description"):
            pdf.ln(2)
            heading("Descripción", 11, 1)
            para(r["description"], 9, 4.5)
        if include_chapters and r.get("chapters"):
            pdf.ln(2)
            heading("Capítulos", 11, 1)
            for c in r["chapters"]:
                para(f"[{T.fmt_ts(float(c.get('start_time') or 0))}] {c.get('title')}", 9, 4.5)
        pdf.ln(2)
        heading("Transcripción", 11, 1)
        last = None
        for p in T.paragraphs(r["segments"], r.get("chapters")):
            if include_chapters and p["chapter"] and p["chapter"] != last:
                pdf.ln(1)
                heading(p["chapter"], 10, 1)
                last = p["chapter"]
            pdf.set_font(fam, "B", 10)
            pdf.set_text_color(20, 60, 160)
            pdf.write(5, f"[{T.fmt_ts(p['start'])}] ", link=core.watch_url(r["id"], p["start"]) if p["start"] >= 1
                      else r["url"])
            pdf.set_text_color(0, 0, 0)
            pdf.set_font(fam, "", 10)
            pdf.write(5, tx(p["text"]))
            pdf.ln(7)
    if missing:
        pdf.add_page()
        pdf.start_section("Videos relevantes no incluidos")
        heading("Videos relevantes no incluidos", 14)
        total = missing_total or len(missing)
        para(f"{total} videos cumplen la seleccion pero no estan en este documento:", 10)
        pdf.ln(2)
        for m in missing:
            pdf.set_font(fam, "B", 9)
            pdf.multi_cell(0, 4.5, tx(m["title"]), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(fam, "", 8)
            pdf.set_text_color(20, 60, 160)
            pdf.cell(0, 4, m["url"], link=m["url"], new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.multi_cell(0, 4, tx(m["reason"]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.5)
        if total > len(missing):
            para(f"... y {total - len(missing)} mas", 9)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    s = core.fold(s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "videos"


def _criteria(**kw: Any) -> str:
    names = {"video_ids": "IDs", "channel": "canal", "title": "título", "description": "descripción",
             "text": "título/descripción", "query": "dicho en el video", "date_from": "desde",
             "date_to": "hasta", "language": "idioma"}
    parts = []
    for k, v in kw.items():
        if v:
            parts.append(f"{names[k]}={len(v)} videos" if k == "video_ids" else f"{names[k]}: {v}")
    return ", ".join(parts) or "todos"


def export_videos(store: core.Store, *, video_ids: list[str] | None = None, channel: str | None = None,
                  title: str | None = None, description: str | None = None, text: str | None = None,
                  query: str | None = None, date_from: str | None = None, date_to: str | None = None,
                  language: str | None = None, limit: int | None = None, format: str = "md",
                  doc_title: str | None = None, include_description: bool = True,
                  include_chapters: bool = True, max_chars_per_file: int = DEFAULT_MAX_CHARS,
                  out_dir: Path | None = None, filename: str | None = None,
                  return_content: bool = False, fetch_missing_videos: bool = False,
                  fetch_limit: int = 50, net: dict[str, Any] | None = None) -> dict[str, Any]:
    """Genera el documento (md, pdf o both) con TODOS los videos que cumplen el filtro (o los
    primeros `limit`) y devuelve rutas, cobertura y estadisticas. Con `fetch_missing_videos`
    primero descarga los que cumplen el filtro y aun no tienen transcripcion."""
    if format not in ("md", "pdf", "both"):
        raise ValueError("format debe ser md, pdf o both")
    fetched = None
    only_query = not (video_ids or channel or title or description or text or date_from or date_to)
    if fetch_missing_videos and only_query:
        fetched = {"note": "fetch_missing necesita canal, IDs u otro filtro ademas de query: query solo "
                           "busca en transcripciones ya descargadas."}
    elif fetch_missing_videos:
        fetched = fetch_missing(store, video_ids=video_ids, channel=channel, title=title,
                                description=description, text=text, date_from=date_from, date_to=date_to,
                                fetch_limit=fetch_limit, describe_first=True, net=net or {})
    sel = collect(store, video_ids=video_ids, channel=channel, title=title, description=description,
                  text=text, query=query, date_from=date_from, date_to=date_to, language=language, limit=limit)
    records = sel["records"]
    if not records:
        out = {"videos": 0, "files": [], "coverage": sel["coverage"], "without_transcript": sel["without_transcript"][:50],
               "hint": "Ningun video seleccionado tiene transcripcion. Usa fetch_missing_videos=true o harvest_channel."}
        if fetched is not None:
            out["fetched"] = fetched
        return out
    crit = _criteria(video_ids=video_ids, channel=channel, title=title, description=description, text=text,
                     query=query, date_from=date_from, date_to=date_to, language=language)
    if not doc_title:
        if len(records) == 1:
            doc_title = records[0]["title"]
        else:
            chans = {r.get("channel") for r in records}
            who = next(iter(chans)) if len(chans) == 1 and None not in chans else "YouTube"
            doc_title = f"{who}: {len(records)} videos" + (f" sobre {query or text or title}" if (query or text or title) else "")
    out_dir = Path(out_dir) if out_dir else store.root / "exports"
    stem = filename or f"{_slug(doc_title)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    stem = re.sub(r"\.(md|pdf)$", "", stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    miss_ids = sel["without_transcript"]
    missing = missing_info(store, miss_ids) if miss_ids else []
    md_docs = render_markdown(records, doc_title=doc_title, criteria=crit, include_description=include_description,
                              include_chapters=include_chapters, query=query, max_chars_per_file=max_chars_per_file,
                              missing=missing, missing_total=len(miss_ids))
    if format in ("md", "both"):
        for n, d in enumerate(md_docs, 1):
            p = out_dir / (f"{stem}.md" if len(md_docs) == 1 else f"{stem}-parte{n}.md")
            p.write_text(d, encoding="utf-8")
            files.append({"path": str(p), "format": "md", "chars": len(d), "approx_tokens": len(d) // CHARS_PER_TOKEN})
    if format in ("pdf", "both"):
        p = render_pdf(records, out_dir / f"{stem}.pdf", doc_title=doc_title, criteria=crit,
                       include_description=include_description, include_chapters=include_chapters, query=query,
                       missing=missing, missing_total=len(miss_ids))
        files.append({"path": str(p), "format": "pdf", "bytes": p.stat().st_size})
    total_chars = sum(len(d) for d in md_docs)
    out: dict[str, Any] = {
        "title": doc_title, "videos": len(records), "files": files,
        "approx_tokens": total_chars // CHARS_PER_TOKEN,
        "videos_included": [{"title": r["title"], "url": r["url"], "language": r["language"]} for r in records],
        "coverage": sel["coverage"], "without_transcript": sel["without_transcript"][:50],
        "truncated_by_limit": sel["truncated"],
    }
    if fetched is not None:
        out["fetched"] = fetched
        if fetched.get("blocked"):
            out["hint"] = ("YouTube limito la IP durante la descarga; el documento incluye lo que ya habia. "
                           "Vuelve a intentarlo mas tarde para completar.")
    if sel["coverage"].get("without_transcript"):
        out.setdefault("hint", f"{sel['coverage']['without_transcript']} videos cumplen el filtro pero no tienen "
                               "transcripcion; usa fetch_missing_videos=true para incluirlos.")
    if return_content:
        out["content"] = md_docs[0] if len(md_docs) == 1 else md_docs
    return out
