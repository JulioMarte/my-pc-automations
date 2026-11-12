"""Tests de busqueda en YouTube: codificacion de filtros y forma de los resultados (sin red)."""

from __future__ import annotations

import base64
import os

import pytest

from yt_channel_transcripts import search as yts


@pytest.mark.parametrize("kw,expected", [
    ({}, "EgIQAQ=="),                                     # solo videos (valor conocido de la web)
    ({"kind": "channel"}, "EgIQAg=="),                    # solo canales
    ({"kind": "playlist"}, "EgIQAw=="),                   # solo playlists
    ({"sort": "date"}, "CAISAhAB"),                       # videos por fecha de subida
    ({"sort": "views"}, "CAMSAhAB"),                      # videos por vistas
    ({"upload_date": "week"}, "EgQIAxAB"),                # videos de esta semana
])
def test_build_sp_coincide_con_los_filtros_de_la_web(kw, expected):
    assert yts.build_sp(**kw) == expected


def test_build_sp_combinado_es_protobuf_valido():
    raw = base64.b64decode(yts.build_sp(sort="date", upload_date="month", duration="long"))
    assert raw == bytes([0x08, 2, 0x12, 6, 0x08, 4, 0x10, 1, 0x18, 2])


def test_build_sp_valida():
    for kw in ({"kind": "x"}, {"sort": "x"}, {"upload_date": "x"}, {"duration": "x"}):
        with pytest.raises(ValueError):
            yts.build_sp(**kw)


def test_search_url_escapa_consulta_y_sp():
    url = yts.search_url("educación & finanzas", sort="date")
    assert url == ("https://www.youtube.com/results?search_query=educaci%C3%B3n+%26+finanzas"
                   "&sp=CAISAhAB")


class FakeSearcher:
    def __init__(self, entries):
        self.entries, self.calls = entries, []

    def __call__(self, url, limit):
        self.calls.append((url, limit))
        return self.entries[:limit]


VIDEO = {"_type": "url", "ie_key": "Youtube", "id": "AcV46e__Deg", "title": "Educacion financiera",
         "channel": "EL TIO BILLETES", "channel_id": "UCZ0_nUh5VpvwuHdkTpDzqwQ", "uploader_id": "@eltiobilletess",
         "duration": 3201, "view_count": 229453, "description": "La diferencia..."}
CHANNEL = {"_type": "url", "ie_key": "YoutubeTab", "id": "UCEEEVvin3iRz_E1Ivf0Ns-A", "title": "Oscar Finanzas",
           "channel_id": "UCEEEVvin3iRz_E1Ivf0Ns-A", "uploader_id": "@OscarDoradoFinanzas",
           "url": "https://www.youtube.com/channel/UCEEEVvin3iRz_E1Ivf0Ns-A", "channel_follower_count": 30700,
           "description": "Canal de educacion financiera"}


def test_search_youtube_videos_filtra_lo_que_no_es_video():
    fs = FakeSearcher([VIDEO, CHANNEL])
    r = yts.search_youtube("educacion financiera", limit=5, sort="views", duration="long", searcher=fs)
    assert fs.calls[0][1] == 5 and "sp=" in fs.calls[0][0]
    assert r["returned"] == 1
    v = r["results"][0]
    assert v == {"type": "video", "id": "AcV46e__Deg", "title": "Educacion financiera",
                 "url": "https://www.youtube.com/watch?v=AcV46e__Deg", "channel": "EL TIO BILLETES",
                 "channel_id": "UCZ0_nUh5VpvwuHdkTpDzqwQ", "handle": "@eltiobilletess", "duration_min": 53.4,
                 "views": 229453, "description": "La diferencia..."}


def test_search_youtube_canales():
    r = yts.search_youtube("finanzas", kind="channel", searcher=FakeSearcher([CHANNEL]))
    c = r["results"][0]
    assert c["channel_id"] == "UCEEEVvin3iRz_E1Ivf0Ns-A" and c["handle"] == "@OscarDoradoFinanzas"
    assert c["url"] == "https://www.youtube.com/@OscarDoradoFinanzas" and c["subscribers"] == 30700


def test_search_youtube_valida_y_limita():
    fs = FakeSearcher([VIDEO])
    with pytest.raises(ValueError):
        yts.search_youtube("  ", searcher=fs)
    with pytest.raises(ValueError):
        yts.search_youtube("x", kind="channel", duration="long", searcher=fs)
    yts.search_youtube("x", limit=1000, searcher=fs)
    assert fs.calls[-1][1] == 100


def test_search_in_channel_usa_el_buscador_del_canal():
    fs = FakeSearcher([VIDEO])
    r = yts.search_in_channel("@QuantumFracture", "neutrinos y hielo", searcher=fs)
    assert fs.calls[0][0] == "https://www.youtube.com/@QuantumFracture/search?query=neutrinos+y+hielo"
    assert r["returned"] == 1 and r["results"][0]["id"] == "AcV46e__Deg"
    yts.search_in_channel("https://www.youtube.com/@x/videos", "q", searcher=fs)
    assert fs.calls[-1][0] == "https://www.youtube.com/@x/search?query=q"
    with pytest.raises(ValueError):
        yts.search_in_channel("https://www.youtube.com/playlist?list=PL1", "q", searcher=fs)


@pytest.mark.network
def test_busqueda_real(request):
    if not (request.config.getoption("--network") or os.environ.get("YT_NETWORK_TESTS") == "1"):
        pytest.skip("usa --network o YT_NETWORK_TESTS=1")
    v = yts.search_youtube("educacion financiera", limit=3)
    assert v["returned"] >= 1 and v["results"][0]["url"].startswith("https://www.youtube.com/watch?v=")
    c = yts.search_youtube("QuantumFracture", kind="channel", limit=3)
    assert any(x.get("channel_id") == "UCbdSYaPD-lr1kW27UJuk8Pw" for x in c["results"])
    ch = yts.search_in_channel("@QuantumFracture", "neutrinos", limit=5)
    assert ch["returned"] >= 1 and all(x["channel_id"] == "UCbdSYaPD-lr1kW27UJuk8Pw" for x in ch["results"])
