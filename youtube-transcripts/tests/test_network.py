"""Prueba real contra YouTube. Solo corre con --network o YT_NETWORK_TESTS=1 (puede
fallar por bloqueos de IP, que no son defectos del codigo)."""

from __future__ import annotations

import os

import pytest

from yt_channel_transcripts import core

pytestmark = pytest.mark.network


def test_canal_real(tmp_path, request):
    if not (request.config.getoption("--network") or os.environ.get("YT_NETWORK_TESTS") == "1"):
        pytest.skip("usa --network o YT_NETWORK_TESTS=1")
    st = core.Store(tmp_path)
    r = core.harvest(st, "@3blue1brown", max_videos=2, list_limit=3, languages=["en"], delay=1)
    assert r["listed"] == 3 and r["blocked"] is None
    assert r["downloaded"] >= 1
    v = core.list_videos(st, "@3blue1brown", only_with_transcript=True)["videos"][0]
    t = core.get_transcript(st, v["url"], max_chars=500)
    assert t["title"] and len(t["transcript"]) > 100
