"""Tests del proveedor Supadata (opener falso: sin red y sin gastar creditos)."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from test_core import CID, FakeYT, IDS  # noqa: F401
from yt_channel_transcripts import catalog, core, supadata


class Resp(io.BytesIO):
    def __init__(self, status, body):
        super().__init__(json.dumps(body).encode())
        self.status = status


class FakeSupa:
    def __init__(self, plan=None):
        self.plan = plan or {}
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, req, timeout=120):
        u = urlparse(req.full_url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.calls.append((u.path, q, dict(req.header_items())))
        if u.path.startswith("/v1/transcript/"):
            return Resp(200, {"status": "completed", "lang": "en",
                              "content": [{"text": "async ok", "offset": 0, "duration": 1000}]})
        vid = q["url"].rsplit("=", 1)[1]
        status, body = self.plan.get(vid, (200, {"lang": "en", "content": [
            {"text": "ion exchange", "offset": 1500, "duration": 2000},
            {"text": "membrane", "offset": 3500, "duration": 1000}]}))
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, io.BytesIO(json.dumps(body).encode()))
        return Resp(status, body)


def test_native_un_credito_y_formato():
    api = FakeSupa()
    r = supadata.fetch("UMI_ITPgirI", ["original", "en"], key="SECRET", opener=api)
    path, q, headers = api.calls[0]
    assert path == "/v1/transcript" and q["mode"] == "native" and q["lang"] == "en" and q["text"] == "false"
    assert headers.get("X-api-key") == "SECRET"
    assert r.status == "ok" and r.source == "supadata" and r.language == "en"
    assert r.segments == [{"start": 1.5, "duration": 2.0, "text": "ion exchange"},
                          {"start": 3.5, "duration": 1.0, "text": "membrane"}]
    supadata.fetch("x", ["original"], key="K", opener=api)
    assert "lang" not in api.calls[-1][1]  # 'original' no es un idioma para Supadata


def test_sin_subtitulos_async_y_errores():
    api = FakeSupa({"a": (206, {"error": "transcript-unavailable"}), "b": (202, {"jobId": "J1"}),
                    "c": (402, {"error": "upgrade-required", "message": "no credits for K"}),
                    "d": (500, {"error": "internal-error"})})
    assert supadata.fetch("a", ["en"], key="K", opener=api).status == "sin_transcripcion"
    r = supadata.fetch("b", ["en"], key="K", opener=api, sleep=lambda s: None)
    assert r.status == "ok" and r.segments[0]["text"] == "async ok" and api.calls[-1][0] == "/v1/transcript/J1"
    with pytest.raises(supadata.SupadataError) as e:
        supadata.fetch("c", ["en"], key="K", opener=api)
    assert "upgrade-required" in str(e.value) and "for K" not in str(e.value).replace("for ***", "")
    assert supadata.fetch("d", ["en"], key="K", opener=api).status == "error"


def test_reintenta_el_429_de_ritmo():
    calls = {"n": 0}
    ok = FakeSupa()

    def opener(req, timeout=120):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "x", {}, io.BytesIO(b'{"error":"limit-exceeded"}'))
        return ok(req, timeout)
    slept = []
    assert supadata.fetch("v", ["en"], key="K", opener=opener, sleep=slept.append).status == "ok"
    assert slept == [2.0]


def test_clave_desde_archivo_y_sin_clave(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SUPADATA_API_KEY", raising=False)
    monkeypatch.setenv("YT_TRANSCRIPTS_DIR", str(tmp_path))
    assert supadata.api_key() is None
    with pytest.raises(supadata.SupadataError, match="Falta la clave"):
        supadata.fetch("v", ["en"])
    (tmp_path / "supadata.key").write_text("  KEYFILE \n", encoding="utf-8")
    assert supadata.api_key() == "KEYFILE"
    monkeypatch.setenv("SUPADATA_API_KEY", "ENVKEY")
    assert supadata.api_key() == "ENVKEY"


def test_harvest_con_supadata_no_toca_youtube(tmp_path: Path, monkeypatch):
    st, yt = Store(tmp_path), FakeYT(IDS[:2])
    core.harvest(st, "@prueba", max_videos=0, **yt.kw())
    core.fetch_metadata(st, "@prueba", lister=yt.lister, enricher=yt.enricher)
    monkeypatch.setenv("YT_TRANSCRIPT_PROVIDER", "supadata")
    monkeypatch.setenv("YT_PACING_FILE", str(tmp_path / "p.json"))
    monkeypatch.setenv("YT_SUPADATA_MIN_SECONDS", "0")
    monkeypatch.setenv("YT_SUPADATA_MAX_SECONDS", "0")
    api = FakeSupa()
    monkeypatch.setattr(supadata, "fetch", lambda vid, langs: supadata.__dict__["_real"](vid, langs, key="K", opener=api))
    supadata._real = _real_fetch
    sub_calls = []
    kw = {**yt.kw(), "sub_fetcher": lambda info, l: sub_calls.append(1)}
    kw.pop("fetcher")  # el proveedor se elige por entorno
    catalog.selection_update(st, "s", add=IDS[:2], channel="@prueba", topic="t")
    r = catalog.process_selection(st, "s", format="md", net=kw)
    assert r["videos"] == 2 and r["fetched"]["downloaded"] == 2 and sub_calls == [] and yt.fetched == []
    assert len(api.calls) == 2 and st.load_transcript(IDS[0])["source"] == "supadata"


_real_fetch = supadata.fetch
Store = core.Store
