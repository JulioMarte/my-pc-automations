"""Tests del documento final MD/PDF (sin red)."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_core import FakeYT, IDS, TITLES  # noqa: F401  (reutiliza el canal falso)
from yt_channel_transcripts import core, document
from yt_channel_transcripts.core import Store, TranscriptResult


@pytest.fixture
def st(tmp_path: Path) -> Store:
    s = Store(tmp_path)
    yt = FakeYT()
    yt.plan = {IDS[3]: TranscriptResult(core.ST_NONE, error="TranscriptsDisabled")}
    core.harvest(s, "@prueba", **yt.kw())
    return s


def test_md_por_ids_respeta_orden_y_reporta_faltantes(st: Store):
    r = document.export_videos(st, video_ids=[IDS[2], IDS[0], IDS[3]], return_content=True)
    md = r["content"]
    assert r["videos"] == 2 and r["without_transcript"] == [IDS[3]]
    assert md.index(TITLES[IDS[2]]) < md.index(TITLES[IDS[0]])
    assert "## Índice" in md and "## 1. La tasa de interés explicada" in md
    assert "### Descripción" in md and "Qué es la tasa de política monetaria." in md
    assert "### Capítulos" in md and "#### Tema" in md and "[1:05] Educación financiera básica" in md
    assert "**Idioma:** es (manual)" in md and "**Fecha:** 2025-12-31 |" in md  # fecha exacta, sin "aprox."
    assert Path(r["files"][0]["path"]).read_text(encoding="utf-8") == md
    assert r["approx_tokens"] == len(md) // 4


def test_md_por_filtros_y_por_lo_dicho(st: Store):
    r = document.export_videos(st, title="inflacion", return_content=True, include_description=False)
    assert [v["title"] for v in r["videos_included"]] == [TITLES[IDS[0]], TITLES[IDS[4]]]
    assert "### Descripción" not in r["content"]
    q = document.export_videos(st, query="financiera", channel="@prueba", limit=2, return_content=True)
    assert q["videos"] == 2 and q["truncated_by_limit"] is True
    assert "**Dónde aparece la búsqueda `financiera`:** [1:05]" in q["content"]
    none = document.export_videos(st, query="inexistente")
    assert none["videos"] == 0 and none["files"] == []


def test_md_partido_en_varios_archivos(st: Store, tmp_path: Path):
    r = document.export_videos(st, channel="@prueba", max_chars_per_file=600, out_dir=tmp_path / "o", filename="x")
    paths = [Path(f["path"]).name for f in r["files"]]
    assert len(paths) > 1 and paths[0] == "x-parte1.md"
    first = Path(r["files"][0]["path"]).read_text(encoding="utf-8")
    assert f"(parte 1 de {len(paths)})" in first
    total = sum(Path(f["path"]).read_text(encoding="utf-8").count("\n## ") for f in r["files"])
    assert total - len(paths) == r["videos"]  # cada video en exactamente un archivo (+ un indice por archivo)


def test_pdf_valido_con_marcadores(st: Store):
    r = document.export_videos(st, channel="@prueba", format="pdf")
    p = Path(r["files"][0]["path"])
    data = p.read_bytes()
    assert data.startswith(b"%PDF-") and r["files"][0]["bytes"] == len(data)
    assert data.count(b"/Outlines") >= 1 and b"youtube.com/watch?v=" in data


def test_pdf_texto_seguro():
    assert document._pdf_text("Hola 😀 ⚛️ niño\x07", True) == "Hola ⚛ niño"
    assert document._pdf_text("niño → ok", False) == "niño ? ok"


def test_validaciones(st: Store):
    with pytest.raises(ValueError):
        document.export_videos(st)  # sin seleccion
    with pytest.raises(ValueError):
        document.export_videos(st, channel="@prueba", format="docx")
