"""Tests de la API oficial (sin red: opener falso)."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from test_core import CID, FakeYT, IDS  # noqa: F401
from yt_channel_transcripts import core, official


class FakeAPI:
    def __init__(self, n_videos: int = 120):
        self.ids = [f"a{i:010d}" for i in range(n_videos)]
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, timeout=30):
        u = urlparse(url)
        ep = u.path.rsplit("/", 1)[1]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.calls.append((ep, q))
        if ep == "channels":
            body = {"items": [{"id": CID, "snippet": {"title": "Canal Prueba", "customUrl": "@prueba"}}]}
        elif ep == "playlistItems":
            start = int(q.get("pageToken", 0))
            chunk = self.ids[start:start + 50]
            body = {"items": [{"contentDetails": {"videoId": v, "videoPublishedAt": "2026-01-02T00:00:00Z"},
                               "snippet": {"title": f"T {v}"}} for v in chunk]}
            if start + 50 < len(self.ids):
                body["nextPageToken"] = str(start + 50)
        elif ep == "videos":
            body = {"items": [{"id": v, "snippet": {"title": f"T {v}", "description": f"desc {v}\n0:00 Intro\n1:00 A\n2:00 B",
                                                    "publishedAt": "2026-01-02T10:00:00Z", "tags": ["x"],
                                                    "channelTitle": "Canal Prueba", "channelId": CID,
                                                    "defaultAudioLanguage": "en"},
                               "contentDetails": {"duration": "PT1H2M3S"}, "statistics": {"viewCount": "7"}}
                              for v in q["id"].split(",") if v in self.ids]}
        else:
            raise AssertionError(ep)
        return io.BytesIO(json.dumps(body).encode())


def test_utilidades():
    assert official.iso_duration("PT1H2M3S") == 3723 and official.iso_duration("PT45S") == 45
    assert official.iso_duration("P1DT1M") == 86460 and official.iso_duration(None) is None
    ch = official.chapters_from_description("hola\n0:00 Intro\n(1:30) - Parte A\n1:02:03 Final")
    assert [(c["start_time"], c["title"]) for c in ch] == [(0, "Intro"), (90, "Parte A"), (3723, "Final")]
    assert ch[0]["end_time"] == 90
    assert official.chapters_from_description("1:00 a\n2:00 b\n3:00 c") == []  # no empieza en 0:00
    assert core._channel_ref("https://www.youtube.com/@Rowow/videos") == "@Rowow"
    assert core._channel_ref(f"https://www.youtube.com/channel/{CID}") == CID
    assert core._channel_ref("Rowow") == "@Rowow"


def test_listado_y_metadatos_paginados():
    api = FakeAPI(120)
    up = official.list_uploads(CID, "K", opener=api)
    assert len(up["videos"]) == 120 and up["exhausted"] and [c[0] for c in api.calls] == ["playlistItems"] * 3
    assert api.calls[0][1]["playlistId"] == "UU" + CID[2:]
    inc = official.list_uploads(CID, "K", known=set(api.ids), opener=api)
    assert len(inc["videos"]) == 10 and not inc["exhausted"]
    api.calls.clear()
    info = official.videos_info(api.ids, "K", opener=api)
    assert len(api.calls) == 3 and len(info) == 120  # 50 por peticion
    m = core.metadata_from_info(info[api.ids[0]])
    assert m["date"] == "2026-01-02" and m["duration"] == 3723 and m["language"] == "en" and len(m["chapters"]) == 3


def test_errores_no_filtran_la_clave():
    def boom(url, timeout=30):
        body = json.dumps({"error": {"message": "API key SECRETA123 not valid", "errors": [{"reason": "keyInvalid"}]}})
        raise urllib.error.HTTPError(url, 400, "bad", {}, io.BytesIO(body.encode()))
    with pytest.raises(official.OfficialAPIError) as e:
        official.videos_info(["x"], "SECRETA123", opener=boom)
    assert "SECRETA123" not in str(e.value) and "keyInvalid" in str(e.value)


def test_fetch_metadata_y_listado_usan_la_api_si_hay_clave(tmp_path: Path, monkeypatch):
    api = FakeAPI(120)
    monkeypatch.setenv("YT_API_KEY", "K")
    monkeypatch.setattr(official.urllib.request, "urlopen", api)
    st = core.Store(tmp_path)
    r = core.fetch_metadata(st, "https://www.youtube.com/@prueba/videos", tab="all", max_videos=500)
    assert r["source"] == "api_oficial" and r["fetched"] == 120 and r["pending"] == 0
    assert r["listed"] == 120 and r["listing_complete"]
    eps = [c[0] for c in api.calls]
    assert eps == ["channels"] + ["playlistItems"] * 3 + ["videos"] * 3  # 7 peticiones para 120 videos
    v = st.videos(CID)[0]
    assert v["has_metadata"] and v["date"] == "2026-01-02" and v["duration"] == 3723
    assert core.find_videos(st, description="desc")["total"] == 120


def test_cuota_agotada_no_cae_a_la_via_web(tmp_path: Path, monkeypatch):
    st, yt = core.Store(tmp_path), FakeYT()
    core.harvest(st, "@prueba", max_videos=0, **yt.kw())
    monkeypatch.setenv("YT_API_KEY", "K")

    def quota(ids, key):
        raise official.OfficialAPIError("YouTube Data API 403 quotaExceeded: x")
    monkeypatch.setattr(official, "videos_info", quota)
    r = core.fetch_metadata(st, "@prueba")
    assert r["fetched"] == 0 and "quotaExceeded" in r["api_error"]
