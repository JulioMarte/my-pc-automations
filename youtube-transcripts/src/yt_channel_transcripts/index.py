"""Indice SQLite FTS5 (biblioteca estandar) para filtrar videos y buscar en transcripciones.

Es un indice *derivado*: la verdad esta en los JSON de la cache, y el indice se
puede reconstruir en cualquier momento con `rebuild`. Ventajas frente a recorrer
los JSON: ranking por relevancia (BM25), busqueda sin tildes ni mayusculas,
prefijos (`econom*`), frases ("tasa de interes"), OR/NOT y velocidad con miles
de videos.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import text as T

SCHEMA_VERSION = 1
TOKENIZER = "unicode61 remove_diacritics 2"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS videos (
  id TEXT PRIMARY KEY, channel_id TEXT, channel TEXT, title TEXT, description TEXT,
  tags TEXT, date TEXT, date_exact INTEGER, duration INTEGER, views INTEGER, url TEXT,
  status TEXT, language TEXT, is_generated INTEGER, words INTEGER, has_metadata INTEGER
);
CREATE INDEX IF NOT EXISTS videos_channel ON videos(channel_id, date);
CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
  title, description, tags, video_id UNINDEXED, tokenize='{TOKENIZER}');
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, chapter, video_id UNINDEXED, start UNINDEXED, tokenize='{TOKENIZER}');
"""

_FTS_SYNTAX = re.compile(r'"|\*|\bOR\b|\bAND\b|\bNOT\b|\bNEAR\b|^-|\s-')
_TOKEN = re.compile(r"[\w]+(?:[-'][\w]+)*\*?", re.UNICODE)


def fts_query(q: str) -> str:
    """Convierte texto libre en una consulta FTS5 segura: cada palabra entre comillas
    (todas deben aparecer). Si el texto ya usa sintaxis FTS5 ("frase", OR, NOT, prefijo*)
    se respeta tal cual; `-palabra` se traduce a NOT."""
    q = q.strip()
    if not q:
        raise ValueError("consulta vacia")
    if _FTS_SYNTAX.search(q):
        # "-x" (estilo buscador) -> NOT "x"
        q = re.sub(r"(^|\s)-(\w+)", r' NOT "\2"', q)
        return q.strip()
    toks = _TOKEN.findall(q)
    if not toks:
        raise ValueError(f"consulta sin palabras: {q!r}")
    return " ".join(f'"{t[:-1]}"*' if t.endswith("*") else f'"{t}"' for t in toks)


def _safe_query(q: str) -> list[str]:
    """Consulta principal y, por si la sintaxis del usuario es invalida, una version
    con cada palabra entre comillas."""
    first = fts_query(q)
    toks = _TOKEN.findall(q.replace('"', " "))
    fallback = " ".join(f'"{t.rstrip("*")}"' for t in toks if t.upper() not in ("OR", "AND", "NOT", "NEAR"))
    return [first] + ([fallback] if fallback and fallback != first else [])


class Index:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not self.path.exists()
        self.db = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()  # una conexion compartida entre hilos (MCP)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        ver = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if ver is None or int(ver[0]) != SCHEMA_VERSION:
            if not fresh and ver is not None:  # esquema viejo: se rehace (es derivado)
                self.db.executescript("DROP TABLE IF EXISTS videos; DROP TABLE IF EXISTS videos_fts;"
                                      "DROP TABLE IF EXISTS chunks_fts;" + SCHEMA)
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
            self.db.commit()
        self.needs_rebuild = fresh

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            try:
                yield self.db
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    # --- escritura -----------------------------------------------------------
    def upsert_video(self, channel_id: str, channel: str | None, v: dict[str, Any],
                     meta: dict[str, Any] | None = None) -> None:
        meta = meta or {}
        desc = meta.get("description")
        tags = " ".join(meta.get("tags") or [])
        row = {
            "id": v["id"], "channel_id": channel_id, "channel": channel, "title": v.get("title") or "",
            "description": desc, "tags": tags or None,
            "date": meta.get("date") or v.get("date"), "date_exact": 1 if meta.get("date") else 0,
            "duration": meta.get("duration") or v.get("duration"), "views": meta.get("views") or v.get("views"),
            "url": v.get("url"), "status": v.get("status"), "language": v.get("language"),
            "is_generated": None if v.get("is_generated") is None else int(bool(v.get("is_generated"))),
            "words": v.get("words"), "has_metadata": 1 if meta else 0,
        }
        with self.tx() as db:
            old = db.execute("SELECT description, tags, has_metadata, date, date_exact FROM videos WHERE id=?",
                             (v["id"],)).fetchone()
            if old and old["has_metadata"] and not meta:  # no pisar metadatos ya obtenidos
                row.update(description=old["description"], tags=old["tags"], has_metadata=1,
                           date=old["date"], date_exact=old["date_exact"])
            cols = ",".join(row)
            db.execute(f"INSERT OR REPLACE INTO videos ({cols}) VALUES ({','.join('?' * len(row))})",
                       tuple(row.values()))
            db.execute("DELETE FROM videos_fts WHERE video_id=?", (v["id"],))
            db.execute("INSERT INTO videos_fts (title, description, tags, video_id) VALUES (?,?,?,?)",
                       (row["title"], row["description"] or "", row["tags"] or "", v["id"]))

    def set_chunks(self, vid: str, paras: list[dict[str, Any]]) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM chunks_fts WHERE video_id=?", (vid,))
            db.executemany("INSERT INTO chunks_fts (text, chapter, video_id, start) VALUES (?,?,?,?)",
                           [(p["text"], p.get("chapter") or "", vid, p["start"]) for p in paras])

    def clear(self) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM videos")
            db.execute("DELETE FROM videos_fts")
            db.execute("DELETE FROM chunks_fts")

    # --- lectura -------------------------------------------------------------
    def _filters(self, *, channel_id: str | None, date_from: str | None, date_to: str | None,
                 min_minutes: float | None, max_minutes: float | None, has_transcript: bool | None,
                 video_ids: list[str] | None, title: str | None, description: str | None,
                 text: str | None) -> tuple[list[str], list[Any]]:
        where: list[str] = []
        args: list[Any] = []
        if channel_id:
            where.append("v.channel_id = ?"); args.append(channel_id)
        if date_from:
            where.append("v.date >= ?"); args.append(date_from)
        if date_to:
            where.append("v.date <= ?"); args.append(date_to)
        if min_minutes is not None:
            where.append("v.duration >= ?"); args.append(int(min_minutes * 60))
        if max_minutes is not None:
            where.append("v.duration <= ?"); args.append(int(max_minutes * 60))
        if has_transcript is True:
            where.append("v.status = 'ok'")
        elif has_transcript is False:
            where.append("COALESCE(v.status,'') <> 'ok'")
        if video_ids:
            where.append(f"v.id IN ({','.join('?' * len(video_ids))})"); args += list(video_ids)
        for col, q in (("title", title), ("description", description), (None, text)):
            if q:
                expr = fts_query(q)
                target = f"{{{col}}} : ({expr})" if col else f"{{title description tags}} : ({expr})"
                where.append("v.id IN (SELECT video_id FROM videos_fts WHERE videos_fts MATCH ?)")
                args.append(target)
        return where, args

    def find_videos(self, *a: Any, **k: Any) -> dict[str, Any]:
        with self.lock:
            return self._find_videos(*a, **k)

    def _find_videos(self, *, channel_id: str | None = None, title: str | None = None,
                    description: str | None = None, text: str | None = None,
                    date_from: str | None = None, date_to: str | None = None,
                    min_minutes: float | None = None, max_minutes: float | None = None,
                    has_transcript: bool | None = None, video_ids: list[str] | None = None,
                    sort: str = "date_desc", limit: int = 50, offset: int = 0) -> dict[str, Any]:
        where, args = self._filters(channel_id=channel_id, date_from=date_from, date_to=date_to,
                                    min_minutes=min_minutes, max_minutes=max_minutes,
                                    has_transcript=has_transcript, video_ids=video_ids,
                                    title=title, description=description, text=text)
        rank_q = text or title or description
        order = {"date_desc": "v.date DESC", "date_asc": "v.date ASC", "views": "v.views DESC",
                 "duration": "v.duration DESC", "title": "v.title COLLATE NOCASE"}.get(sort)
        join, sel, jargs = "", "NULL AS rank, NULL AS snip", []
        if sort == "relevance" and rank_q:
            col = "{title description tags}" if text else ("{title}" if title else "{description}")
            join = "JOIN (SELECT video_id, bm25(videos_fts, 5.0, 1.0, 2.0) AS rank FROM videos_fts " \
                   "WHERE videos_fts MATCH ?) r ON r.video_id = v.id"
            jargs = [f"{col} : ({fts_query(rank_q)})"]
            sel, order = "r.rank AS rank, NULL AS snip", "r.rank ASC"
        elif sort == "relevance" or order is None:
            order = "v.date DESC"
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.db.execute(f"SELECT COUNT(*) FROM videos v {join}{wsql}", jargs + args).fetchone()[0]
        rows = self.db.execute(
            f"SELECT v.*, {sel} FROM videos v {join}{wsql} ORDER BY {order}, v.id LIMIT ? OFFSET ?",
            jargs + args + [limit, offset]).fetchall()
        desc_q = description or text
        out = []
        for r in rows:
            d = r["description"] or ""
            item = {"id": r["id"], "title": r["title"], "url": r["url"], "date": r["date"],
                    "date_exact": bool(r["date_exact"]), "duration_min": round((r["duration"] or 0) / 60, 1),
                    "channel": r["channel"], "status": r["status"], "language": r["language"],
                    "words": r["words"], "has_metadata": bool(r["has_metadata"]),
                    "description": _excerpt(d, desc_q, 240) if d else None}
            out.append({k: v for k, v in item.items() if v is not None})
        return {"total": total, "offset": offset,
                "next_offset": offset + limit if offset + limit < total else None, "videos": out}

    def search_chunks(self, *a: Any, **k: Any) -> dict[str, Any]:
        with self.lock:
            return self._search_chunks(*a, **k)

    def _search_chunks(self, query: str, *, max_results: int = 20, per_video: int = 3,
                      **filters: Any) -> dict[str, Any]:
        where, args = self._filters(**{k: filters.get(k) for k in (
            "channel_id", "date_from", "date_to", "min_minutes", "max_minutes", "video_ids",
            "title", "description", "text")}, has_transcript=None)
        wsql = (" AND " + " AND ".join(where)) if where else ""
        last_err: Exception | None = None
        for q in _safe_query(query):
            try:
                rows = self.db.execute(
                    "SELECT c.video_id, c.start, c.chapter, bm25(chunks_fts) AS rank, "
                    "snippet(chunks_fts, 0, '**', '**', ' ... ', 40) AS snip, "
                    "v.title, v.url, v.date, v.channel "
                    f"FROM chunks_fts c JOIN videos v ON v.id = c.video_id "
                    f"WHERE chunks_fts MATCH ?{wsql} ORDER BY rank LIMIT 2000",
                    [f"{{text}} : ({q})"] + args).fetchall()
                break
            except sqlite3.OperationalError as exc:
                last_err = exc
        else:
            raise ValueError(f"Consulta invalida: {query!r} ({last_err})")
        per: dict[str, int] = {}
        results = []
        for r in rows:
            n = per.get(r["video_id"], 0)
            per[r["video_id"]] = n + 1
            if n >= per_video or len(results) >= max_results:
                continue
            start = float(r["start"])
            results.append({k: v for k, v in {
                "title": r["title"], "video_url": r["url"], "date": r["date"], "channel": r["channel"],
                "chapter": r["chapter"] or None, "at": T.fmt_ts(start),
                "link": f"https://www.youtube.com/watch?v={r['video_id']}&t={int(start)}s",
                "snippet": r["snip"]}.items() if v is not None})
        return {"query": query, "total_matches": len(rows), "videos_matched": len(per),
                "returned": len(results), "results": results}


def _excerpt(text: str, query: str | None, size: int) -> str:
    """Fragmento de la descripcion alrededor de la primera palabra buscada (o el inicio)."""
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) <= size:
        return flat
    pos = 0
    if query:
        from .core import fold
        ff = fold(flat)
        for tok in _TOKEN.findall(query):
            if tok.upper() in ("OR", "AND", "NOT", "NEAR"):
                continue
            i = ff.find(fold(tok.rstrip("*")))
            if i >= 0:
                pos = max(0, i - size // 3)
                break
    return ("..." if pos else "") + flat[pos: pos + size] + ("..." if pos + size < len(flat) else "")


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
