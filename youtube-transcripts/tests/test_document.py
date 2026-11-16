"""Tests del documento final MD/PDF (sin red)."""

from __future__ import annotations

import re
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
    total = sum(len(re.findall(r"\n## \d+\. ", Path(f["path"]).read_text(encoding="utf-8"))) for f in r["files"])
    assert total == r["videos"]  # cada video en exactamente un archivo
    last = Path(r["files"][-1]["path"]).read_text(encoding="utf-8")
    assert "## Videos relevantes no incluidos" in last and IDS[3] in last  # apendice solo al final
    assert "Videos relevantes" not in first


# --- apendice de no incluidos -------------------------------------------------------

def test_apendice_con_motivo_en_md_y_pdf(st: Store):
    r = document.export_videos(st, video_ids=[IDS[0], IDS[3], "zzzzzzzzzzz"], format="both", return_content=True)
    md = r["content"]
    assert "## Videos relevantes no incluidos" in md and "2 videos cumplen la seleccion" in md
    assert f"{TITLES[IDS[3]]} - https://www.youtube.com/watch?v={IDS[3]} - el video no tiene subtitulos" in md
    assert "zzzzzzzzzzz - https://www.youtube.com/watch?v=zzzzzzzzzzz - no esta descargado" in md
    pdf = Path(r["files"][1]["path"]).read_bytes()
    assert pdf.count(b"/Title") >= 3  # marcadores: 1 video + apendice (+ titulo del documento)


def test_fetch_missing_baja_ids_fuera_del_listado_por_via_suelta(tmp_path: Path):
    s, yt = Store(tmp_path), FakeYT()
    core.harvest(s, "@prueba", max_videos=0, **yt.kw())
    directo = "liveliveliv"  # p. ej. un directo encontrado por la busqueda, no esta en /videos
    r = document.export_videos(s, channel="@prueba", video_ids=[IDS[0], directo], fetch_missing_videos=True,
                               net=yt.kw())
    assert sorted(yt.fetched) == sorted([IDS[0], directo]) and r["videos"] == 2


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


# --- todos los que cumplen el filtro, cobertura y descarga de faltantes ---------

def _parcial(tmp_path: Path, n_transcritos: int, metadata: bool = True):
    """Canal listado completo pero con solo los primeros n videos descargados."""
    s, yt = Store(tmp_path), FakeYT()
    core.harvest(s, "@prueba", max_videos=n_transcritos, metadata=metadata, **yt.kw())
    return s, yt


def test_sin_tope_incluye_todos_y_reporta_cobertura(tmp_path: Path):
    s, yt = _parcial(tmp_path, 1)
    r = document.export_videos(s, title="inflacion")  # IDS[0] descargado, IDS[4] no
    assert r["videos"] == 1 and r["truncated_by_limit"] is False
    assert r["coverage"] == {"matching": 2, "with_transcript": 1, "without_transcript": 1}
    assert r["without_transcript"] == [IDS[4]] and "fetch_missing_videos" in r["hint"]
    many = [core.watch_url(v) for v in IDS]
    core.harvest(s, "@prueba", max_videos=10, **yt.kw())
    assert document.export_videos(s, video_ids=many)["videos"] == 5  # sin el tope viejo


def test_fetch_missing_descarga_lo_que_cumple_el_filtro_y_exporta(tmp_path: Path):
    s, yt = _parcial(tmp_path, 1)
    yt.fetched.clear()
    r = document.export_videos(s, channel="@prueba", title="inflacion", fetch_missing_videos=True,
                               net=yt.kw(), return_content=True)
    assert yt.fetched == [IDS[4]]  # solo el que faltaba y cumple el filtro
    assert r["videos"] == 2 and r["coverage"]["without_transcript"] == 0
    assert r["fetched"]["downloaded"] == 1 and TITLES[IDS[4]] in r["content"]


def test_filtro_de_descripcion_avisa_y_baja_metadatos_que_faltan(tmp_path: Path):
    s, yt = _parcial(tmp_path, 0, metadata=False)  # solo listado: sin descripciones
    r = document.export_videos(s, channel="@prueba", description="precios")
    assert r["videos"] == 0 and r["coverage"]["not_evaluated_no_metadata"] == 5
    r = document.export_videos(s, channel="@prueba", description="precios", fetch_missing_videos=True,
                               net=yt.kw())
    assert r["fetched"]["metadata_fetched"] == 5 and r["videos"] == 2
    assert {v["title"] for v in r["videos_included"]} == {TITLES[IDS[0]], TITLES[IDS[4]]}
    assert "not_evaluated_no_metadata" not in r["coverage"]


def test_fetch_missing_respeta_limite_y_bloqueo(tmp_path: Path):
    s, yt = _parcial(tmp_path, 0)
    r = document.export_videos(s, channel="@prueba", fetch_missing_videos=True, fetch_limit=2, net=yt.kw())
    assert r["fetched"]["downloaded"] == 2 and r["videos"] == 2 and r["coverage"]["without_transcript"] == 3
    yt.plan = {v: core.BlockedError("429") for v in IDS}
    r = document.export_videos(s, channel="@prueba", fetch_missing_videos=True, net=yt.kw())
    assert r["fetched"]["blocked"] == "429" and r["videos"] == 2 and "limito" in r["hint"]


def test_fetch_missing_solo_con_query_no_descarga(tmp_path: Path):
    s, yt = _parcial(tmp_path, 1)
    yt.fetched.clear()
    r = document.export_videos(s, query="financiera", fetch_missing_videos=True, net=yt.kw())
    assert yt.fetched == [] and "query" in r["fetched"]["note"] and r["videos"] == 1


def test_pdf_partido_igual_que_el_md_sin_cortar_videos(st: Store, tmp_path: Path):
    r = document.export_videos(st, channel="@prueba", format="both", max_chars_per_file=600,
                               out_dir=tmp_path / "o", filename="x")
    mds = [f for f in r["files"] if f["format"] == "md"]
    pdfs = [f for f in r["files"] if f["format"] == "pdf"]
    assert len(pdfs) == len(mds) > 1 and Path(pdfs[0]["path"]).name == "x-parte1.pdf"
    assert sum(f["videos"] for f in pdfs) == r["videos"]
    assert all(Path(f["path"]).read_bytes().startswith(b"%PDF-") for f in pdfs)
    assert b"Videos relevantes no incluidos" not in Path(pdfs[0]["path"]).read_bytes()
    assert document.group_by_size([5, 5, 20, 1], 10) == [[0, 1], [2], [3]]
    assert document.group_by_size([5, 5], 0) == [[0, 1]]
