"""Tests unitarios de core: sin red (lister/fetcher/enricher falsos)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from yt_channel_transcripts import core
from yt_channel_transcripts.core import BlockedError, Store, TranscriptResult

CID = "UC" + "a" * 22


def vid(n: int) -> str:
    return f"v{n:010d}"


IDS = [vid(i) for i in range(5)]
TITLES = {IDS[0]: "Inflación en 2026", IDS[1]: "Cómo invertir en bolsa",
          IDS[2]: "La tasa de interés explicada", IDS[3]: "Vlog de viaje", IDS[4]: "Inflación y salarios"}
DESCS = {IDS[0]: "Hablamos del Banco Central y los precios.", IDS[1]: "Guía para principiantes: ETF y acciones.",
         IDS[2]: "Qué es la tasa de política monetaria.", IDS[3]: "Un día en Santo Domingo.",
         IDS[4]: "Por qué los salarios no suben como los precios."}


class FakeYT:
    """Simula yt-dlp + youtube-transcript-api y cuenta las llamadas."""

    def __init__(self, ids: list[str] | None = None):
        self.ids = list(ids or IDS)
        self.list_calls: list[tuple] = []
        self.fetched: list[str] = []
        self.enriched: list[str] = []
        self.plan: dict[str, TranscriptResult | Exception] = {}
        self.sub_plan: dict[str, TranscriptResult] = {}

    def lister(self, url, limit, known=None):
        self.list_calls.append((url, limit, None if known is None else len(known)))
        vids, streak, exhausted = [], 0, True
        for i, v in enumerate(self.ids):
            if limit and len(vids) >= limit:
                exhausted = False
                break
            vids.append({"id": v, "title": TITLES.get(v, f"Video {v}"), "url": core.watch_url(v),
                         "duration": 600 + 60 * i, "date": "2026-01-%02d" % (28 - i), "views": 100 * (i + 1)})
            if known is not None:
                streak = streak + 1 if v in known else 0
                if streak >= core.STOP_AFTER_KNOWN:
                    exhausted = False
                    break
        return {"channel_id": CID, "channel": "Canal Prueba", "handle": "@prueba",
                "channel_url": f"https://www.youtube.com/channel/{CID}", "videos": vids, "exhausted": exhausted}

    def fetcher(self, v, langs):
        self.fetched.append(v)
        r = self.plan.get(v)
        if isinstance(r, Exception):
            raise r
        return r or ok()

    def enricher(self, v):
        self.enriched.append(v)
        return {"id": v, "title": TITLES.get(v), "description": DESCS.get(v, ""), "tags": ["economia"],
                "upload_date": "20251231", "duration": 777, "view_count": 5, "channel": "Canal Prueba",
                "chapters": [{"start_time": 0, "end_time": 60, "title": "Intro"},
                             {"start_time": 60, "end_time": 200, "title": "Tema"}]}

    def sub_fetcher(self, info, langs):
        return self.sub_plan.get(info["id"], TranscriptResult(core.ST_ERROR, error="yt-dlp: sin formato json3"))

    def kw(self, **extra):
        return {"lister": self.lister, "fetcher": self.fetcher, "enricher": self.enricher,
                "sub_fetcher": self.sub_fetcher, "delay": 0, **extra}


def ok(text="hola mundo"):
    return TranscriptResult(core.ST_OK, "es", False,
                            [{"start": 0.0, "duration": 2.0, "text": text},
                             {"start": 65.5, "duration": 2.0, "text": "Educación financiera\nbásica"}])


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
    assert core.pick_transcript(ts, ["es", "en"]) == T("en", False)


def test_pick_respeta_variantes_regionales():
    assert core.pick_transcript([T("en", False), T("es-419", False)], ["es", "en"]).language_code == "es-419"


def test_pick_cae_a_la_automatica_original():
    assert core.pick_transcript([T("de", False), T("fr", True)], ["es"]) == T("fr", True)
    assert core.pick_transcript([T("de", False)], ["es"]) == T("de", False)
    assert core.pick_transcript([], ["es"]) is None


# --- respaldo yt-dlp: subtitulos json3 ----------------------------------------

def _json3(*texts):
    return {"events": [{"tStartMs": 1000 * i, "dDurationMs": 900, "segs": [{"utf8": t}]} for i, t in enumerate(texts)]
            + [{"tStartMs": 99, "aAppend": 1}]}


def test_subtitulos_ytdlp_eligen_original_y_parsean_json3():
    info = {"id": "x", "subtitles": {"live_chat": []},
            "automatic_captions": {"fr": [{"ext": "json3", "url": "u-fr"}],
                                   "es-orig": [{"ext": "vtt", "url": "v"}, {"ext": "json3", "url": "u-es"}]}}
    urls = []
    r = core.subtitles_from_info(info, ["en"], get_json=lambda u: urls.append(u) or _json3("hola", " ", "mundo"))
    assert urls == ["u-es"]  # la automatica original, no la traduccion al frances
    assert (r.status, r.language, r.is_generated, r.source) == ("ok", "es", True, "yt-dlp")
    assert [s["text"] for s in r.segments] == ["hola", "mundo"] and r.segments[1]["start"] == 2.0


def test_subtitulos_ytdlp_manual_en_idioma_pedido_gana():
    info = {"subtitles": {"en": [{"ext": "json3", "url": "m-en"}]},
            "automatic_captions": {"es-orig": [{"ext": "json3", "url": "a-es"}]}}
    urls = []
    core.subtitles_from_info(info, ["en", "es"], get_json=lambda u: urls.append(u) or _json3("hi"))
    assert urls == ["m-en"]


def test_subtitulos_ytdlp_sin_pistas_y_429():
    assert core.subtitles_from_info({}, ["es"]).status == core.ST_NONE
    info = {"automatic_captions": {"es-orig": [{"ext": "json3", "url": "u"}]}}

    def boom(u):
        raise RuntimeError("HTTP Error 429: Too Many Requests")
    with pytest.raises(BlockedError):
        core.subtitles_from_info(info, ["es"], get_json=boom)


# --- harvest -------------------------------------------------------------------

def test_harvest_incremental_reanudable_y_con_metadatos(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT()
    r1 = core.harvest(st, "@prueba", max_videos=2, **yt.kw())
    assert (r1["downloaded"], r1["pending"], r1["new_videos"], r1["metadata_fetched"]) == (2, 3, 5, 2)
    assert yt.fetched == IDS[:2] and yt.enriched == IDS[:2]
    r2 = core.harvest(st, "@prueba", max_videos=10, **yt.kw())
    assert (r2["downloaded"], r2["pending"], r2["new_videos"]) == (3, 0, 0)
    assert yt.fetched == IDS and yt.enriched == IDS  # nada se pidio dos veces
    v0 = st.videos(CID)[0]
    assert v0["date"] == "2025-12-31" and v0["duration"] == 777 and v0["has_metadata"]  # fecha exacta
    assert json.loads(st.meta_path(CID, IDS[0]).read_text(encoding="utf-8"))["description"] == DESCS[IDS[0]]
    assert r2["hint"] == "Completo." and r2["sources"] == {"youtube-transcript-api": 3}


def test_listado_incremental_tras_listado_completo(tmp_path: Path):
    st = Store(tmp_path)
    many = [vid(i) for i in range(40)]
    yt = FakeYT(many)
    r = core.harvest(st, "@prueba", max_videos=0, **yt.kw())
    assert r["listing"] == "completo" and r["listing_complete"] and yt.list_calls[-1][2] is None
    nuevo = vid(99)
    yt.ids = [nuevo] + many
    r = core.harvest(st, "@prueba", max_videos=0, **yt.kw())
    assert r["listing"] == "incremental" and r["new_videos"] == 1
    assert r["listed"] == 1 + core.STOP_AFTER_KNOWN  # dejo de paginar al ver 10 conocidos seguidos
    assert len(st.videos(CID)) == 41 and st.videos(CID)[0]["id"] == nuevo


def test_listado_parcial_no_activa_incremental(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT([vid(i) for i in range(30)])
    r = core.harvest(st, "@prueba", max_videos=0, list_limit=5, **yt.kw())
    assert r["listing"] == "parcial" and not r["listing_complete"]
    r = core.harvest(st, "@prueba", max_videos=0, **yt.kw())  # ahora el canal completo
    assert r["listing"] == "completo" and r["listed"] == 30 and r["listing_complete"]


def test_harvest_estados_reintento_y_respaldo(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT(IDS[:3])
    yt.plan = {IDS[0]: TranscriptResult(core.ST_NONE, error="TranscriptsDisabled"),
               IDS[1]: TranscriptResult(core.ST_ERROR, error="timeout")}
    r = core.harvest(st, "@prueba", **yt.kw())
    assert (r["downloaded"], r["without_transcript"], r["errors"], r["pending"]) == (1, 1, 1, 0)
    yt.fetched.clear()
    core.harvest(st, "@prueba", **yt.kw())
    assert yt.fetched == []  # sin retry_errors no se reintenta
    del yt.plan[IDS[1]]  # el error transitorio ya paso
    yt.fetched.clear()
    r = core.harvest(st, "@prueba", retry_errors=True, **yt.kw())
    assert yt.fetched == [IDS[1]] and r["downloaded"] == 1  # el permanente (IDS[0]) nunca se reintenta


def test_respaldo_ytdlp_cuando_api_no_tiene_pista(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT(IDS[:1])
    yt.plan = {IDS[0]: TranscriptResult(core.ST_NONE, error="NoTranscriptFound")}
    yt.sub_plan = {IDS[0]: TranscriptResult(core.ST_OK, "es", True, [{"start": 0, "duration": 1, "text": "x"}],
                                            source="yt-dlp")}
    r = core.harvest(st, "@prueba", metadata=False, **yt.kw())
    assert r["downloaded"] == 1 and yt.enriched == [IDS[0]]  # pidio info solo para el respaldo


def test_bloqueo_para_y_conserva(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT()
    yt.plan = {IDS[2]: BlockedError("429")}
    r = core.harvest(st, "@prueba", max_videos=5, **yt.kw())
    assert r["blocked"] == "429" and r["downloaded"] == 2 and r["pending"] == 3
    assert "limito" in r["hint"]
    assert sum(v["status"] == core.ST_OK for v in st.videos(CID)) == 2
    # tras el bloqueo no se intenta ningun otro video ni otro endpoint en esa corrida
    assert yt.fetched == IDS[:3]


def test_bloqueo_en_metadatos_detiene(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT()

    def enr(v):
        raise BlockedError("Sign in to confirm you're not a bot")
    r = core.harvest(st, "@prueba", **{**yt.kw(), "enricher": enr})
    assert r["blocked"] and r["attempted"] == 0 and yt.fetched == []


def test_error_de_metadatos_no_frena_transcripcion(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT(IDS[:1])

    def enr(v):
        raise RuntimeError("extractor roto")
    r = core.harvest(st, "@prueba", **{**yt.kw(), "enricher": enr})
    assert r["downloaded"] == 1 and "extractor roto" in st.videos(CID)[0]["meta_error"]


def test_harvest_title_filter_y_video_ids(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT()
    r = core.harvest(st, "@prueba", title_filter="inflacion", **yt.kw())  # sin tilde
    assert sorted(yt.fetched) == sorted([IDS[0], IDS[4]]) and r["pending"] == 0
    yt.fetched.clear()
    core.harvest(st, "@prueba", video_ids=[core.watch_url(IDS[2])], **yt.kw())
    assert yt.fetched == [IDS[2]]


def test_harvest_respeta_delay_y_list_limit(tmp_path: Path):
    sleeps: list[float] = []
    yt = FakeYT()
    core.harvest(Store(tmp_path), "@prueba", list_limit=3, **{**yt.kw(), "delay": 2.5, "sleep": sleeps.append})
    assert yt.list_calls == [("https://www.youtube.com/@prueba/videos", 3, None)]
    assert sleeps == [2.5, 2.5]


def test_fetch_metadata_sin_transcribir(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT()
    r = core.fetch_metadata(st, "@prueba", max_videos=3, **{k: v for k, v in yt.kw().items()
                                                            if k in ("lister", "enricher", "delay")})
    assert r["fetched"] == 3 and r["pending"] == 2 and yt.fetched == []
    found = core.find_videos(st, "@prueba", description="precios")
    assert [v["id"] for v in found["videos"]] == [IDS[0]]  # IDS[4] aun sin metadatos


# --- lectura -----------------------------------------------------------------------

@pytest.fixture
def poblado(tmp_path: Path) -> Store:
    st = Store(tmp_path)
    core.harvest(st, "@prueba", **FakeYT().kw())
    return st


@pytest.mark.parametrize("ref", ["@prueba", "prueba", "Canal Prueba", CID,
                                 "https://www.youtube.com/@prueba", f"https://www.youtube.com/channel/{CID}"])
def test_resolve_por_cualquier_referencia(poblado: Store, ref):
    assert poblado.resolve(ref) == CID


def test_resolve_desconocido(poblado: Store):
    with pytest.raises(KeyError):
        poblado.resolve("@otro")


def test_find_videos_por_titulo_descripcion_y_texto(poblado: Store):
    ids = lambda r: [v["id"] for v in r["videos"]]  # noqa: E731
    assert ids(core.find_videos(poblado, "@prueba", title="inflacion")) == [IDS[0], IDS[4]]
    assert ids(core.find_videos(poblado, title='"tasa de interes"')) == [IDS[2]]
    assert ids(core.find_videos(poblado, description="precios")) == [IDS[0], IDS[4]]
    assert ids(core.find_videos(poblado, description="precios -salarios")) == [IDS[0]]
    assert ids(core.find_videos(poblado, text="ETF OR viaje")) == [IDS[1], IDS[3]]
    assert ids(core.find_videos(poblado, title="invert*")) == [IDS[1]]
    r = core.find_videos(poblado, description="banco central")
    assert "Banco Central" in r["videos"][0]["description"]  # conserva el texto original


def test_find_videos_filtros_y_orden(poblado: Store):
    r = core.find_videos(poblado, has_transcript=True, sort="views", limit=2)
    assert r["total"] == 5 and r["next_offset"] == 2
    assert core.find_videos(poblado, date_from="2026-01-01")["total"] == 0  # fechas exactas: 2025-12-31
    assert core.find_videos(poblado, max_minutes=12.0)["total"] == 0  # 777 s > 12 min
    assert core.find_videos(poblado, min_minutes=12.0)["total"] == 5
    rel = core.find_videos(poblado, text="inflacion", sort="relevance")
    assert {v["id"] for v in rel["videos"]} == {IDS[0], IDS[4]}
    with pytest.raises(ValueError):
        core.find_videos(poblado, title='"sin cerrar')


def test_get_transcript_formatos_y_paginacion(poblado: Store):
    full = core.get_transcript(poblado, IDS[0], max_chars=0)["transcript"]
    assert full == "### Intro\n\n[0:00] hola mundo\n\n### Tema\n\n[1:05] Educación financiera básica"
    txt = core.get_transcript(poblado, IDS[0], format="text", max_chars=0)
    assert txt["transcript"] == "hola mundo Educación financiera básica" and txt["next_offset"] is None
    p1 = core.get_transcript(poblado, core.watch_url(IDS[0]), format="text", max_chars=10)
    p2 = core.get_transcript(poblado, IDS[0], format="text", max_chars=10, offset=p1["next_offset"])
    assert p1["transcript"] + p2["transcript"] == txt["transcript"][:20]
    seg = core.get_transcript(poblado, IDS[0], format="segments")["transcript"]
    assert seg.splitlines() == ["[0:00] hola mundo", "[1:05] Educación financiera básica"]
    assert p1["title"] == TITLES[IDS[0]] and p1["date"] == "2025-12-31"


def test_get_transcript_fuera_de_cache_lo_baja_guarda_e_indexa(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT()
    r = core.get_transcript(st, "dQw4w9WgXcQ", fetcher=yt.fetcher, enricher=yt.enricher, sub_fetcher=yt.sub_fetcher)
    assert "hola mundo" in r["transcript"]
    core.get_transcript(st, "dQw4w9WgXcQ", fetcher=yt.fetcher)
    assert yt.fetched == ["dQw4w9WgXcQ"]  # segunda vez desde cache
    assert core.search(st, "financiera")["videos_matched"] == 1
    yt.plan = {"aaaaaaaaaaa": TranscriptResult(core.ST_NONE, error="TranscriptsDisabled")}
    bad = core.get_transcript(st, "aaaaaaaaaaa", fetcher=yt.fetcher, enricher=yt.enricher, sub_fetcher=yt.sub_fetcher)
    assert bad["status"] == core.ST_NONE and "transcript" not in bad


def test_get_video_info(poblado: Store, tmp_path: Path):
    info = core.get_video_info(poblado, IDS[1])
    assert info["description"] == DESCS[IDS[1]] and info["chapters"][1]["title"] == "Tema"
    assert info["transcript"]["available"] and info["transcript"]["words"] == 5
    st2, yt = Store(tmp_path / "otra"), FakeYT()
    assert core.get_video_info(st2, "dQw4w9WgXcQ", enricher=yt.enricher)["transcript"] == {"available": False}
    core.get_video_info(st2, "dQw4w9WgXcQ", enricher=yt.enricher)
    assert yt.enriched == ["dQw4w9WgXcQ"]  # cacheado


def test_search_relevancia_tildes_capitulo_y_filtros(poblado: Store):
    r = core.search(poblado, "educacion FINANCIERA")
    assert r["videos_matched"] == 5 and r["returned"] == 5
    hit = r["results"][0]
    assert hit["at"] == "1:05" and hit["link"].endswith("&t=65s") and hit["chapter"] == "Tema"
    assert "**Educación**" in hit["snippet"]  # resaltado con el texto original
    assert core.search(poblado, "financiera", title="inflacion")["videos_matched"] == 2
    assert core.search(poblado, "financiera", description="ETF")["videos_matched"] == 1
    assert core.search(poblado, "financiera", video_ids=[IDS[3]])["results"][0]["title"] == TITLES[IDS[3]]
    assert core.search(poblado, "inexistente")["total_matches"] == 0
    assert core.search(poblado, "financ*", max_results=2)["returned"] == 2
    assert core.search(poblado, 'pregunta? "rara')["total_matches"] == 0  # sintaxis rota: no revienta


def test_indice_se_reconstruye_desde_json(poblado: Store):
    poblado.index.clear()
    assert core.find_videos(poblado, title="inflacion")["total"] == 0
    r = core.rebuild_index(poblado)
    assert r == {"videos": 5, "transcripts": 5, "path": str(poblado.root / "index.sqlite")}
    assert core.find_videos(poblado, title="inflacion")["total"] == 2
    poblado.close()
    (poblado.root / "index.sqlite").unlink()
    for extra in ("index.sqlite-wal", "index.sqlite-shm"):
        (poblado.root / extra).unlink(missing_ok=True)
    assert core.search(Store(poblado.root), "financiera")["videos_matched"] == 5  # se rehace solo


def test_export_formatos(poblado: Store, tmp_path: Path):
    j = core.export(poblado, "@prueba", "jsonl", format="text")
    rows = [json.loads(x) for x in Path(j["path"]).read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 5 and set(rows[0]) == {"title", "url", "date", "language", "description", "transcript"}
    assert rows[0]["url"] == core.watch_url(IDS[0]) and rows[0]["description"] == DESCS[IDS[0]]
    c = core.export(poblado, "@prueba", "csv", tmp_path / "x.csv", title_filter="inflacion")
    with open(c["path"], encoding="utf-8-sig", newline="") as fh:
        assert [r["title"] for r in csv.DictReader(fh)] == [TITLES[IDS[0]], TITLES[IDS[4]]]
    m = Path(core.export(poblado, "@prueba", "md")["path"]).read_text(encoding="utf-8")
    assert m.startswith("# Canal Prueba") and m.count("\n## ") == 5 and "[1:05]" in m and "**Descripcion:**" in m
    with pytest.raises(ValueError):
        core.export(poblado, "@prueba", "xml")


def test_con_metadatos_basta_una_peticion_de_subtitulos(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT(IDS[:3])
    yt.sub_plan = {v: TranscriptResult(core.ST_OK, "es", True, [{"start": 0, "duration": 1, "text": "z"}],
                                       source="yt-dlp") for v in IDS[:3]}
    r = core.harvest(st, "@prueba", **yt.kw())
    assert r["downloaded"] == 3 and r["sources"] == {"yt-dlp": 3}
    assert yt.fetched == []  # la API (2-3 peticiones por video) no hizo falta


def test_sin_subtitulos_segun_ytdlp_no_se_pregunta_a_la_api(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT(IDS[:1])
    yt.sub_plan = {IDS[0]: TranscriptResult(core.ST_NONE, error="yt-dlp: el video no tiene subtitulos")}
    r = core.harvest(st, "@prueba", **yt.kw())
    assert r["without_transcript"] == 1 and yt.fetched == []


# --- idioma original / idioma pedido -------------------------------------------

def test_por_defecto_el_idioma_es_original(monkeypatch):
    monkeypatch.delenv("YT_LANGS", raising=False)
    assert core.default_languages() == ["original"]
    monkeypatch.setenv("YT_LANGS", "en,original")
    assert core.default_languages() == ["en", "original"]


def test_original_evita_traducciones_subidas_como_manuales():
    # canal en ingles que sube una traduccion IA al espanol como pista "manual"
    ts = [T("es", False), T("en", False), T("en", True)]
    assert core.pick_transcript(ts, ["original"]) == T("en", False)  # manual en el idioma hablado
    assert core.pick_transcript([T("es", False), T("en", True)], ["original"]) == T("en", True)


def test_idioma_pedido_y_caida_al_original():
    ts = [T("es", False), T("es", True), T("en", False)]
    assert core.pick_transcript(ts, ["en"]) == T("en", False)
    assert core.pick_transcript([T("es", False), T("es", True)], ["en", "original"]) == T("es", False)
    assert core.pick_transcript([T("es", True)], ["en"]) == T("es", True)  # sin ingles: el original


def test_original_sin_pista_automatica_usa_la_pista_de_metadatos():
    ts = [T("de", False), T("pt", False)]
    assert core.pick_transcript(ts, ["original"]) == T("de", False)  # sin pistas: la primera
    assert core.pick_transcript(ts, ["original", "pt"]) == T("pt", False)


def test_subtitulos_ytdlp_modo_original():
    info = {"subtitles": {"en": [{"ext": "json3", "url": "m-en"}]},
            "automatic_captions": {"es-orig": [{"ext": "json3", "url": "a-es"}],
                                   "en": [{"ext": "json3", "url": "a-en-traducida"}]}}
    urls = []
    r = core.subtitles_from_info(info, ["original"], get_json=lambda u: urls.append(u) or _json3("hola"))
    assert urls == ["a-es"] and r.language == "es"
    info["subtitles"]["es"] = [{"ext": "json3", "url": "m-es"}]
    core.subtitles_from_info(info, ["original"], get_json=lambda u: urls.append(u) or _json3("hola"))
    assert urls[-1] == "m-es"  # manual en el idioma original gana a la automatica
    core.subtitles_from_info({"language": "pt", "subtitles": {"en": [{"ext": "json3", "url": "x"}],
                                                               "pt": [{"ext": "json3", "url": "m-pt"}]}},
                             ["original"], get_json=lambda u: urls.append(u) or _json3("ola"))
    assert urls[-1] == "m-pt"  # sin ASR: idioma declarado del video


def test_harvest_pasa_el_idioma_declarado_como_respaldo(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT(IDS[:1])
    seen = []
    base_enr = yt.enricher
    r = core.harvest(st, "@prueba", languages=["original"],
                     **{**yt.kw(), "enricher": lambda v: {**base_enr(v), "language": "pt"},
                        "fetcher": lambda v, l: seen.append(list(l)) or ok()})
    assert r["downloaded"] == 1 and seen == [["original", "pt"]]


def test_get_transcript_en_otro_idioma_se_guarda_aparte(poblado: Store):
    calls = []

    def fetch_en(v, langs):
        calls.append(list(langs))
        return TranscriptResult(core.ST_OK, "en", False, [{"start": 0, "duration": 1, "text": "hello world"}])

    r = core.get_transcript(poblado, IDS[0], languages=["en"], format="text", fetcher=fetch_en)
    assert r["language"] == "en" and r["transcript"] == "hello world" and calls == [["en"]]
    r = core.get_transcript(poblado, IDS[0], languages=["en"], format="text", fetcher=fetch_en)
    assert len(calls) == 1  # la variante quedo en cache
    assert core.get_transcript(poblado, IDS[0], format="text")["language"] == "es"  # la principal no cambio
    assert core.search(poblado, "hello")["total_matches"] == 0  # las variantes no se indexan
    assert core.get_transcript(poblado, IDS[0], languages=["es"], format="text")["language"] == "es"


def test_get_transcript_idioma_inexistente_devuelve_la_guardada_con_nota(poblado: Store):
    r = core.get_transcript(poblado, IDS[1], languages=["en"], fetcher=lambda v, l: ok())  # solo hay "es"
    assert r["language"] == "es" and "No hay pista en 'en'" in r["note"]


def test_find_videos_por_idioma(tmp_path: Path):
    st, yt = Store(tmp_path), FakeYT(IDS[:2])
    yt.plan = {IDS[1]: TranscriptResult(core.ST_OK, "en-US", True, [{"start": 0, "duration": 1, "text": "x"}])}
    core.harvest(st, "@prueba", **yt.kw())
    assert [v["id"] for v in core.find_videos(st, language="en")["videos"]] == [IDS[1]]
    assert [v["id"] for v in core.find_videos(st, language="es")["videos"]] == [IDS[0]]
