"""Tests del limitador (reloj y sueno falsos: no espera de verdad)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from yt_channel_transcripts import core, pacing


class Clock:
    def __init__(self):
        self.t = 1_000_000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 2))
        self.t += s


@pytest.fixture
def pc(tmp_path: Path):
    c = Clock()
    return pacing.Pacer(tmp_path / "p.json", clock=c, sleep=c.sleep, rng=random.Random(1)), c


def test_ritmo_con_intervalo_aleatorio(pc):
    p, c = pc
    p.before("transcript")
    assert c.slept == []  # la primera no espera
    p.before("transcript")
    lo, hi, _ = pacing.DEFAULTS["transcript"]
    assert len(c.slept) == 1 and lo <= c.slept[0] <= hi
    p.before("page")  # otra clase: no espera por la anterior
    assert len(c.slept) == 1


def test_presupuesto_por_hora(pc, monkeypatch):
    monkeypatch.setenv("YT_PAGE_PER_HOUR", "3")
    monkeypatch.setenv("YT_PAGE_MIN_SECONDS", "0")
    monkeypatch.setenv("YT_PAGE_MAX_SECONDS", "0")
    p, c = pc
    for _ in range(3):
        p.before("page")
    with pytest.raises(pacing.PausedError) as e:
        p.before("page")
    assert "Presupuesto de 3" in str(e.value)
    c.t += 3601
    p.before("page")  # una hora despues vuelve a haber cupo


def test_pausa_escalonada_y_persistente(pc, tmp_path: Path):
    p, c = pc
    u1 = p.blocked("transcript")
    assert u1 - c.t == 3600
    with pytest.raises(pacing.PausedError):
        p.before("transcript")
    p.before("page")  # un bloqueo de subtitulos no frena paginas
    c.t = u1 + 1
    p.before("transcript")
    u2 = p.blocked("transcript")
    assert u2 - c.t == 7200  # segundo bloqueo seguido: el doble
    other = pacing.Pacer(tmp_path / "p.json", clock=c, sleep=c.sleep)  # otro proceso, mismo archivo
    with pytest.raises(pacing.PausedError):
        other.before("transcript")
    c.t = u2 + pacing.STRIKE_RESET + 1
    p.before("transcript")
    assert p.blocked("transcript") - c.t == 3600  # 24 h sin bloqueos: la escalada se reinicia


def test_bloqueo_de_paginas_frena_tambien_subtitulos(pc):
    p, c = pc
    p.blocked("page")
    with pytest.raises(pacing.PausedError):
        p.before("transcript")


def test_tope_de_24_horas(pc):
    p, c = pc
    for _ in range(10):
        until = p.blocked("page")
    assert until - c.t == pacing.MAX_COOLDOWN


def test_decorador_pausa_sin_peticion_y_registra_bloqueo(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YT_PACING_FILE", str(tmp_path / "g.json"))
    monkeypatch.setenv("YT_TRANSCRIPT_MIN_SECONDS", "0")
    monkeypatch.setenv("YT_TRANSCRIPT_MAX_SECONDS", "0")
    calls = []

    @core._net("transcript")
    def fetch(x):
        calls.append(x)
        if x == "boom":
            raise core.BlockedError("429")
        return x

    assert fetch("ok") == "ok"
    with pytest.raises(core.BlockedError, match="pausa automatica"):
        fetch("boom")
    with pytest.raises(core.BlockedError, match="Pausa preventiva"):
        fetch("otra")
    assert calls == ["ok", "boom"]  # durante la pausa no se llamo a la red
    assert pacing.get_pacer().status()["transcript"]["consecutive_blocks"] == 1
