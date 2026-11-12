"""Tests unitarios de core: sin red (lister/fetcher falsos)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from yt_channel_transcripts import core
from yt_channel_transcripts.core import BlockedError, Store, TranscriptResult

CID = "UC" + "a" * 22


def make_lister(ids: list[str], calls: list | None = None):
    def lister(url: str, limit):
        if calls is not None:
            calls.append((url, limit))
        vids = [{"id": v, "title": f"Video {v}", "url": core.watch_url(v), "duration": 60,
                 "date": "2026-01-0%d" % (i % 9 + 1), "views": 1} for i, v in enumerate(ids)]
        return {"channel_id": CID, "channel": "Canal Prueba", "handle": "@prueba",
                "channel_url": f"https://www.youtube.com/channel/{CID}",
                "videos": vids[:limit] if limit else vids}
    return lister


def ok(text="hola mundo"):
    return TranscriptResult(core.ST_OK, "es", False,
                            [{"start": 0.0, "duration": 2.0, "text": text},
                             {"start": 65.5, "duration": 2.0, "text": "Educación financiera\nbásica"}])


def vid(n: int) -> str:
    return f"v{n:010d}"


IDS = [vid(i) for i in range(5)]


# --- normalizacion -----------------------------------------------------------

@pytest.mark.parametrize("inp,expected", [
    ("@canal", "https://www.youtube.com/@canal/videos"),
    ("canal", "https://www.youtube.com/@canal/videos"),
    (CID, f"https://www.youtube.com/channel/{CID}/videos"),
    ("https://www.youtube.com/@canal/featured", "https://www.youtube.com/@canal/videos"),
    ("youtube.com/@canal?si=x", "https://youtube.com/@canal/videos"),
])
def test_channel_url(inp, expected):
    assert core.channel_url(inp) == expected


def test_channel_url_tab_y_playlist():
    assert core.channel_url("@c", "streams").endswith("/@c/streams")
    pl = "https://www.youtube.com/playlist?list=PL123"
    assert core.channel_url(pl) == pl
    with pytest.raises(ValueError):
        core.channel_url("@c", "comunidad")


@pytest.mark.parametrize("inp", ["dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3",
                                 "https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/shorts/dQw4w9WgXcQ"])
def test_video_id(inp):
    assert core.video_id(inp) == "dQw4w9WgXcQ"


def test_video_id_invalido():
    with pytest.raises(ValueError):
        core.video_id("no-es-un-video")


# --- seleccion de idioma ------------------------------------------------------

@dataclass
class T:
    language_code: str
    is_generated: bool


def test_pick_prefiere_manual_en_orden_de_idiomas():
    ts = [T("en", True), T("en", False), T("es", True)]
    assert core.pick_transcript(ts, ["es", "en"]) == T("en", False)  # manual gana a automatica


def test_pick_respeta_orden_y_variantes_regionales():
    ts = [T("en", False), T("es-419", False)]
    assert core.pick_transcript(ts, ["es", "en"]).language_code == "es-419"


def test_pick_cae_a_la_automatica_original():
    ts = [T("de", False), T("fr", True)]
    assert core.pick_transcript(ts, ["es"]) == T("fr", True)
    assert core.pick_transcript([T("de", False)], ["es"]) == T("de", False)
    assert core.pick_transcript([], ["es"]) is None


# --- harvest -------------------------------------------------------------------

def test_harvest_incremental_y_reanudable(tmp_path: Path):
    st = Store(tmp_path)
    fetched: list[str] = []

    def fetcher(v, langs):
        fetched.append(v)
        return ok()

    r1 = core.harvest(st, "@prueba", max_videos=2, lister=make_lister(IDS), fetcher=fetcher, delay=0)
    assert (r1["downloaded"], r1["pending"], r1["new_videos"]) == (2, 3, 5)
    assert fetched == IDS[:2]  # los mas recientes primero
    r2 = core.harvest(st, "@prueba", max_videos=10, lister=make_lister(IDS), fetcher=fetcher, delay=0)
    assert (r2["downloaded"], r2["pending"], r2["new_videos"]) == (3, 0, 0)
    assert fetched == IDS  # nada se pidio dos veces
    assert r2["total_with_transcript"] == 5 and r2["hint"] == "Completo."


def test_harvest_video_nuevo_aparece_arriba(tmp_path: Path):
    st = Store(tmp_path)
    core.harvest(st, "@prueba", lister=make_lister(IDS), fetcher=lambda v, l: ok(), delay=0)
    nuevo = vid(99)
    r = core.harvest(st, "@prueba", lister=make_lister([nuevo] + IDS), fetcher=lambda v, l: ok(), delay=0)
    assert r["new_videos"] == 1 and r["downloaded"] == 1
    assert st.videos(CID)[0]["id"] == nuevo


def test_harvest_estados_y_reintento(tmp_path: Path):
    st = Store(tmp_path)
    plan = {IDS[0]: TranscriptResult(core.ST_NONE, error="TranscriptsDisabled"),
            IDS[1]: TranscriptResult(core.ST_ERROR, error="timeout")}
    r = core.harvest(st, "@prueba", lister=make_lister(IDS[:3]),
                     fetcher=lambda v, l: plan.get(v, ok()), delay=0)
    assert (r["downloaded"], r["without_transcript"], r["errors"], r["pending"]) == (1, 1, 1, 0)
    # sin retry_errors no se reintenta; con retry_errors si, y el permanente nunca
    again: list[str] = []
    core.harvest(st, "@prueba", lister=make_lister(IDS[:3]),
                 fetcher=lambda v, l: again.append(v) or ok(), delay=0)
    assert again == []
    core.harvest(st, "@prueba", lister=make_lister(IDS[:3]), retry_errors=True,
                 fetcher=lambda v, l: again.append(v) or ok(), delay=0)
    assert again == [IDS[1]]


def test_harvest_bloqueo_para_y_conserva_lo_bajado(tmp_path: Path):
    st = Store(tmp_path)
    n = {"c": 0}

    def fetcher(v, l):
        n["c"] += 1
        if n["c"] == 3:
            raise BlockedError("429")
        return ok()

    r = core.harvest(st, "@prueba", max_videos=5, lister=make_lister(IDS), fetcher=fetcher, delay=0)
    assert r["blocked"] == "429" and r["downloaded"] == 2 and r["pending"] == 3
    assert "bloqueo" in r["hint"]
    assert sum(v["status"] == core.ST_OK for v in st.videos(CID)) == 2


def test_harvest_respeta_delay_y_list_limit(tmp_path: Path):
    sleeps: list[float] = []
    calls: list = []
    core.harvest(Store(tmp_path), "@prueba", list_limit=3, lister=make_lister(IDS, calls),
                 fetcher=lambda v, l: ok(), delay=2.5, sleep=sleeps.append)
    assert calls == [("https://www.youtube.com/@prueba/videos", 3)]
    assert sleeps == [2.5, 2.5]  # entre videos, no despues del ultimo


# --- lectura -----------------------------------------------------------------------

@pytest.fixture
def poblado(tmp_path: Path) -> Store:
    st = Store(tmp_path)
    core.harvest(st, "@prueba", lister=make_lister(IDS[:2]), fetcher=lambda v, l: ok(), delay=0)
    return st


@pytest.mark.parametrize("ref", ["@prueba", "prueba", "Canal Prueba", CID,
                                 "https://www.youtube.com/@prueba", f"https://www.youtube.com/channel/{CID}"])
def test_resolve_por_cualquier_referencia(poblado: Store, ref):
    assert poblado.resolve(ref) == CID


def test_resolve_desconocido(poblado: Store):
    with pytest.raises(KeyError):
        poblado.resolve("@otro")


def test_list_videos_paginado(poblado: Store):
    r = core.list_videos(poblado, "@prueba", limit=1)
    assert r["total"] == 2 and r["next_offset"] == 1
    v = r["videos"][0]
    assert v["title"] == f"Video {IDS[0]}" and v["url"].endswith(IDS[0]) and v["status"] == "ok"


def test_get_transcript_paginado_y_timestamps(poblado: Store):
    full = core.get_transcript(poblado, IDS[0], max_chars=0)
    assert full["transcript"] == "hola mundo Educación financiera básica"
    assert full["next_offset"] is None and full["title"] == f"Video {IDS[0]}"
    p1 = core.get_transcript(poblado, core.watch_url(IDS[0]), max_chars=10)
    p2 = core.get_transcript(poblado, IDS[0], max_chars=10, offset=p1["next_offset"])
    assert p1["transcript"] + p2["transcript"] == full["transcript"][:20]
    ts = core.get_transcript(poblado, IDS[0], timestamps=True)["transcript"]
    assert ts.splitlines()[0] == "[0:00] hola mundo" and "[1:05]" in ts


def test_get_transcript_fuera_de_cache_lo_baja_y_guarda(tmp_path: Path):
    st = Store(tmp_path)
    calls: list[str] = []
    r = core.get_transcript(st, "dQw4w9WgXcQ", fetcher=lambda v, l: calls.append(v) or ok())
    assert r["transcript"].startswith("hola mundo")
    core.get_transcript(st, "dQw4w9WgXcQ", fetcher=lambda v, l: calls.append(v) or ok())
    assert calls == ["dQw4w9WgXcQ"]  # segunda vez desde cache
    bad = core.get_transcript(st, "aaaaaaaaaaa",
                              fetcher=lambda v, l: TranscriptResult(core.ST_NONE, error="TranscriptsDisabled"))
    assert bad["status"] == core.ST_NONE and "transcript" not in bad


def test_search_sin_tildes_cruza_segmentos_y_enlaza_al_segundo(poblado: Store):
    r = core.search(poblado, "educacion FINANCIERA basica")
    assert r["total_matches"] == 2  # un acierto por video
    hit = r["results"][0]
    assert hit["at"] == "1:05" and hit["link"].endswith("&t=65s")
    assert "Educación financiera básica" in hit["snippet"]  # el fragmento conserva tildes y mayusculas
    assert core.search(poblado, "mundo educacion")["total_matches"] == 2  # frase entre dos segmentos
    assert core.search(poblado, "inexistente")["total_matches"] == 0
    assert core.search(poblado, "hola", max_results=1)["returned"] == 1


def test_export_formatos(poblado: Store, tmp_path: Path):
    j = core.export(poblado, "@prueba", "jsonl")
    rows = [json.loads(x) for x in Path(j["path"]).read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and set(rows[0]) == {"title", "url", "date", "language", "transcript"}
    assert rows[0]["url"] == core.watch_url(IDS[0])
    c = core.export(poblado, "@prueba", "csv", tmp_path / "x.csv")
    with open(c["path"], encoding="utf-8-sig", newline="") as fh:
        assert list(csv.DictReader(fh))[1]["title"] == f"Video {IDS[1]}"
    m = Path(core.export(poblado, "@prueba", "md")["path"]).read_text(encoding="utf-8")
    assert m.startswith("# Canal Prueba") and m.count("\n## ") == 2
    with pytest.raises(ValueError):
        core.export(poblado, "@prueba", "xml")
