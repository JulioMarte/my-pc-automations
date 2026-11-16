"""Limpieza de transcripciones y agrupacion en parrafos con marca de tiempo.

Las transcripciones de YouTube vienen en segmentos de 2-5 segundos, a menudo sin
puntuacion (las automaticas) y con etiquetas como "[Musica]". Para un modelo es
mucho mas util leer parrafos de ~1 minuto con su minuto exacto, que puede citar.
"""

from __future__ import annotations

import re
from typing import Any

# Etiquetas de sonido cortas: [Musica], [Music], [Aplausos], [Risas], (applause)...
_TAG_RE = re.compile(r"\[[^\[\]]{1,30}\]|\((?:m[uú]sica|music|aplausos|applause|risas|laughter)\)", re.I)
_WS_RE = re.compile(r"\s+")
_SENT_END = (".", "?", "!", "…", "。", "?", "!")
_SENT_SPLIT = re.compile(r"[.?!…][\"'»”)\]]?\s+(?=\S)")

PARAGRAPH_TARGET = 45.0  # segundos: a partir de aqui se corta en el siguiente final de frase
PARAGRAPH_MAX = 75.0  # segundos: corte forzado (transcripciones sin puntuacion)


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def clean_text(text: str) -> str:
    """Quita etiquetas de sonido y normaliza espacios. Puede devolver ''."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def clean_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Segmentos limpios: sin etiquetas, sin vacios y sin repeticiones consecutivas
    (los subtitulos 'rodantes' repiten la linea anterior)."""
    out: list[dict[str, Any]] = []
    for s in segments:
        t = clean_text(s.get("text", ""))
        if not t or (out and out[-1]["text"] == t):
            continue
        out.append({"start": s["start"], "duration": s.get("duration", 0), "text": t})
    return out


def paragraphs(segments: list[dict[str, Any]], chapters: list[dict[str, Any]] | None = None,
               clean: bool = True) -> list[dict[str, Any]]:
    """Agrupa segmentos en parrafos {start, end, text, chapter}. Corta al empezar un
    capitulo, al pasar PARAGRAPH_TARGET en un final de frase, o al llegar a PARAGRAPH_MAX."""
    segs = clean_segments(segments) if clean else [
        {"start": s["start"], "duration": s.get("duration", 0), "text": _WS_RE.sub(" ", s["text"]).strip()}
        for s in segments if s.get("text", "").strip()]
    chap_starts = sorted((float(c.get("start_time", 0)), c.get("title") or "") for c in chapters or [])

    def chapter_at(t: float) -> str | None:
        name = None
        for start, title in chap_starts:
            if start <= t + 0.5:
                name = title
            else:
                break
        return name

    out: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []

    def flush() -> None:
        if cur:
            last = cur[-1]
            out.append({"start": cur[0]["start"], "end": round(last["start"] + last["duration"], 2),
                        "chapter": chapter_at(cur[0]["start"]),
                        "text": " ".join(s["text"] for s in cur)})
            cur.clear()

    for s in segs:
        if cur:
            span = s["start"] - cur[0]["start"]
            new_chapter = chapter_at(s["start"]) != chapter_at(cur[0]["start"])
            sentence_done = cur[-1]["text"].endswith(_SENT_END)
            if new_chapter or (span >= PARAGRAPH_TARGET and sentence_done):
                flush()
            elif span >= PARAGRAPH_TARGET:
                # El final de frase suele caer dentro de un segmento: cortar ahi mismo.
                m = None
                for m in _SENT_SPLIT.finditer(s["text"]):
                    pass
                if m is not None:
                    head, tail = s["text"][: m.end()].strip(), s["text"][m.end():].strip()
                    cur.append({**s, "text": head})
                    flush()
                    if not tail:
                        continue
                    s = {**s, "text": tail}
                elif span >= PARAGRAPH_MAX:
                    flush()
        cur.append(s)
    flush()
    return out


def render(segments: list[dict[str, Any]], fmt: str = "paragraphs",
           chapters: list[dict[str, Any]] | None = None, clean: bool = True) -> str:
    """fmt: paragraphs ('[1:05] texto', parrafos separados por linea en blanco y
    titulos de capitulo), text (texto corrido) o segments (una linea por segmento)."""
    if fmt == "segments":
        segs = clean_segments(segments) if clean else segments
        return "\n".join(f"[{fmt_ts(s['start'])}] {s['text']}" for s in segs)
    if fmt == "text":
        segs = clean_segments(segments) if clean else segments
        return " ".join(s["text"].replace("\n", " ") for s in segs)
    if fmt != "paragraphs":
        raise ValueError("format debe ser paragraphs, text o segments")
    lines: list[str] = []
    last_chapter = None
    for p in paragraphs(segments, chapters, clean):
        if p["chapter"] and p["chapter"] != last_chapter:
            lines.append(f"### {p['chapter']}")
            last_chapter = p["chapter"]
        lines.append(f"[{fmt_ts(p['start'])}] {p['text']}")
    return "\n\n".join(lines)
