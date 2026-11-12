"""Tests del flujo de revision completa: catalogo -> seleccion -> proceso (sin red)."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_core import CID, DESCS, FakeYT, IDS, TITLES  # noqa: F401
from yt_channel_transcripts import catalog, core
from yt_channel_transcripts.core import Store


class UploadsYT(FakeYT):
    """Como FakeYT, pero la playlist de subidas (UU...) trae ademas un Short."""

    def lister(self, url, limit, known=None):
        r = super().lister(url, limit, known)
        if "list=UU" in url:
            r["videos"].append({"id": "shortshort1", "title": "Short sobre inflacion", "url": core.watch_url("shortshort1"),
                                "duration": 40, "date": "2026-01-01", "views": 9})
            r["channel_id"] = None  # las playlists a veces no traen channel_id
        return r


def test_listado_all_usa_la_playlist_de_subidas(tmp_path: Path):
    st, yt = Store(tmp_path), UploadsYT()
    r = core.fetch_metadata(st, "@prueba", tab="all", **{k: v for k, v in yt.kw().items() if k in ("lister", "enricher")},
                            delay=0)
    assert yt.list_calls[0][:2] == ("https://www.youtube.com/@prueba/videos", 1)  # sondeo para el ID
    assert yt.list_calls[1][0] == "https://www.youtube.com/playlist?list=UU" + CID[2:]
    assert r["channel_id"] == CID and r["fetched"] == 6 and r["pending"] == 0
    assert st.resolve("@prueba") == CID


def test_fetch_metadata_concurrente_y_bloqueo(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT([f"x{i:010d}" for i in range(30)])
    core.harvest(st, "@prueba", max_videos=0, **yt.kw())
    r = core.fetch_metadata(st, "@prueba", concurrency=4, lister=yt.lister, enricher=yt.enricher, delay=0)
    assert r["fetched"] == 30 and r["pending"] == 0 and sorted(yt.enriched) == sorted(yt.ids)
    st2, yt2 = Store(tmp_path / "b"), FakeYT([f"y{i:010d}" for i in range(30)])
    core.harvest(st2, "@prueba", max_videos=0, **yt2.kw())
    n = {"c": 0}

    def enr(v):
        n["c"] += 1
        if n["c"] > 5:
            raise core.BlockedError("Sign in to confirm")
        return yt2.enricher(v)
    r = core.fetch_metadata(st2, "@prueba", concurrency=2, lister=yt2.lister, enricher=enr, delay=0)
    assert r["blocked"] and r["fetched"] == 5 and r["pending"] == 25 and n["c"] <= 7  # deja de enviar


@pytest.fixture
def st(tmp_path: Path) -> Store:
    s, yt = Store(tmp_path), FakeYT()
    core.harvest(s, "@prueba", max_videos=0, **yt.kw())
    core.fetch_metadata(s, "@prueba", max_videos=3, lister=yt.lister, enricher=yt.enricher, delay=0)
    return s


def test_catalogo_compacto_paginado_con_y_sin_metadatos(st: Store):
    r = catalog.catalog(st, "@prueba", limit=4, description_chars=30)
    assert r["total"] == 5 and r["with_metadata"] == 3 and r["next_offset"] == 4
    assert r["videos"][0] == f"{IDS[0]} | 2025-12-31 | 12:57 | {TITLES[IDS[0]]} | Hablamos del Banco Central y…"
    assert r["videos"][3].endswith("| Vlog de viaje | (sin descripcion todavia)")
    last = catalog.catalog(st, "@prueba", offset=4)
    assert last["next_offset"] is None and len(last["videos"]) == 1


def test_seleccion_persistente(st: Store):
    r = catalog.selection_update(st, "Economía básica", add=[IDS[0], core.watch_url(IDS[4]), IDS[0]],
                                 channel="@prueba", topic="economia", reviewed_until=100)
    assert (r["added"], r["total"], r["reviewed_until"]) == (2, 2, 100)
    r = catalog.selection_update(st, "economia basica", add=[IDS[2]], remove=[IDS[4]], reviewed_until=50)
    assert (r["added"], r["removed"], r["total"], r["reviewed_until"]) == (1, 1, 2, 100)  # mismo slug; no retrocede
    show = catalog.selection_show(st, "Economía básica")
    assert show["videos"] == [f"{IDS[0]} | pendiente | {TITLES[IDS[0]]}", f"{IDS[2]} | pendiente | {TITLES[IDS[2]]}"]
    assert catalog.selection_list(st)[0]["total"] == 2
    with pytest.raises(KeyError):
        catalog.selection_show(st, "no existe")


def test_procesar_seleccion_baja_solo_la_lista_y_genera_un_pdf(st: Store):
    yt = FakeYT()
    catalog.selection_update(st, "eco", add=[IDS[0], IDS[2]], channel="@prueba", topic="economia")
    r = catalog.process_selection(st, "eco", net=yt.kw())
    assert sorted(yt.fetched) == sorted([IDS[0], IDS[2]])  # nada fuera de la lista
    assert r["videos"] == 2 and len(r["files"]) == 1 and r["files"][0]["path"].endswith("eco.pdf")
    assert r["title"] == "@prueba: economia"
    assert catalog.selection_show(st, "eco")["last_export"]["videos"] == 2
    yt.fetched.clear()
    catalog.selection_update(st, "eco", add=[IDS[1]])
    r = catalog.process_selection(st, "eco", format="md", net=yt.kw())
    assert yt.fetched == [IDS[1]] and r["videos"] == 3  # reanuda: solo lo nuevo


def test_procesar_con_bloqueo_regenera_al_reintentar(st: Store):
    yt = FakeYT()
    yt.plan = {IDS[2]: core.BlockedError("429")}
    catalog.selection_update(st, "eco", add=[IDS[0], IDS[2]], channel="@prueba", topic="economia")
    r = catalog.process_selection(st, "eco", format="md", net=yt.kw())
    assert r["videos"] == 1 and r["coverage"]["without_transcript"] == 1 and "process_selection" in r["hint"]
    yt.plan = {}
    r = catalog.process_selection(st, "eco", format="md", net=yt.kw())
    assert r["videos"] == 2 and r["coverage"]["without_transcript"] == 0


def test_seleccion_vacia(st: Store):
    catalog.selection_update(st, "vacia", channel="@prueba")
    with pytest.raises(ValueError):
        catalog.process_selection(st, "vacia")


def test_quita_texto_repetido_del_canal(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT()
    core.harvest(st, "@prueba", max_videos=0, **yt.kw())
    pie = "\n\nSuscribete GRATIS!\nhttps://twitter.com/canal"
    enr = lambda v: {**yt.enricher(v), "description": DESCS[v] + pie}  # noqa: E731
    core.fetch_metadata(st, "@prueba", lister=yt.lister, enricher=enr, delay=0)
    r = catalog.catalog(st, "@prueba")
    assert r["videos"][0].endswith(f"| {DESCS[IDS[0]]}")  # sin el pie comun ni la URL
    assert catalog.clean_description("Hola\nhttps://x.y/z\nvisita www.ej.com hoy", set()) == "Hola visita www.ej.com hoy"
