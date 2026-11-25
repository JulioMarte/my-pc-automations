"""Tests de descubrimiento por tema (sin red)."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_core import CID, DESCS, FakeYT, IDS, TITLES  # noqa: F401
from yt_channel_transcripts import core, topic
from yt_channel_transcripts.core import Store


def test_terms_query():
    assert topic.terms_query(["inflacion", "costo de vida", "precio*", ' "x" ']) == \
        '"inflacion" OR "costo de vida" OR precio* OR "x"'
    with pytest.raises(ValueError):
        topic.terms_query(["  "])


class FakeChannelSearch:
    def __init__(self, by_term):
        self.by_term, self.urls = by_term, []

    def __call__(self, url, limit):
        self.urls.append(url)
        term = url.split("query=")[1].replace("+", " ")
        return [{"id": v, "title": TITLES.get(v, "Directo " + v), "channel_id": CID, "duration": 300,
                 "description": "desc de youtube"} for v in self.by_term.get(term, [])][:limit]


@pytest.fixture
def st(tmp_path: Path) -> Store:
    s = Store(tmp_path)
    yt = FakeYT()
    core.harvest(s, "@prueba", max_videos=2, **yt.kw())  # IDS[0], IDS[1] con transcripcion y metadatos
    return s


def test_candidatos_por_varias_vias(st: Store):
    fs = FakeChannelSearch({"precios": [IDS[4], "liveliveliv"], "inflacion": [IDS[0]]})
    r = topic.find_topic_candidates(st, "@prueba", ["inflacion", "precios"], lister=FakeYT().lister, searcher=fs)
    by = {c["id"]: c for c in r["candidates"]}
    assert set(by) == {IDS[0], IDS[4], "liveliveliv"}
    assert by[IDS[0]]["sources"] == ["titulo", "descripcion", "youtube:inflacion"]  # 3 vias
    assert by[IDS[0]]["has_transcript"] and by[IDS[0]]["description"] == DESCS[IDS[0]]
    assert by[IDS[4]]["sources"] == ["titulo", "youtube:precios"] and not by[IDS[4]]["has_transcript"]
    assert by["liveliveliv"]["status"] == "fuera_del_listado" and by["liveliveliv"]["title"] == "Directo liveliveliv"
    assert r["candidates"][0]["id"] == IDS[0]  # mas vias primero
    assert r["listed_videos"] == 5 and r["videos_without_metadata"] == 3
    assert fs.urls[0] == "https://www.youtube.com/@prueba/search?query=inflacion"


def test_candidatos_por_lo_dicho_y_sin_youtube(st: Store):
    r = topic.find_topic_candidates(st, "@prueba", ["financiera"], use_youtube_search=False,
                                    lister=FakeYT().lister)
    assert {c["id"] for c in r["candidates"]} == {IDS[0], IDS[1]}
    assert all(c["sources"] == ["transcripcion"] for c in r["candidates"])


def test_bloqueo_de_busqueda_no_rompe(st: Store):
    def boom(url, limit):
        raise core.BlockedError("429")
    r = topic.find_topic_candidates(st, "@prueba", ["inflacion"], lister=FakeYT().lister, searcher=boom)
    assert {c["id"] for c in r["candidates"]} == {IDS[0], IDS[4]} and "limitada" in r["notes"][0]


def test_titulos_de_videos_fuera_del_listado_llegan_al_apendice(st: Store):
    from yt_channel_transcripts import document
    fs = FakeChannelSearch({"precios": ["liveliveliv"]})
    topic.find_topic_candidates(st, "@prueba", ["precios"], lister=FakeYT().lister, searcher=fs)
    r = document.export_videos(st, video_ids=[IDS[0], "liveliveliv"], return_content=True)
    assert "Directo liveliveliv - https://www.youtube.com/watch?v=liveliveliv - fuera del listado" in r["content"]
