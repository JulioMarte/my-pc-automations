"""Tests de limpieza y parrafos."""

from __future__ import annotations

from yt_channel_transcripts import text as T


def seg(start, text, dur=3.0):
    return {"start": start, "duration": dur, "text": text}


def test_clean_quita_etiquetas_y_repeticiones():
    segs = [seg(0, "[Música]"), seg(1, "hola  [Music] a todos"), seg(2, "hola a todos"), seg(3, "(aplausos)"),
            seg(4, "[corchetes con un texto bastante largo que no es etiqueta de sonido]")]
    out = T.clean_segments(segs)
    assert [s["text"] for s in out] == ["hola a todos",
                                        "[corchetes con un texto bastante largo que no es etiqueta de sonido]"]


def test_parrafos_cortan_en_final_de_frase_tras_objetivo():
    segs = [seg(i * 5, f"frase {i}." if i == 10 else f"palabra {i}") for i in range(20)]
    ps = T.paragraphs(segs)
    assert ps[0]["start"] == 0 and ps[0]["text"].endswith("frase 10.")  # 50 s >= 45 y fin de frase
    assert ps[1]["start"] == 55


def test_parrafos_corte_forzado_sin_puntuacion():
    ps = T.paragraphs([seg(i * 5, f"w{i}") for i in range(40)])  # 200 s sin puntos
    assert all(p2["start"] - p1["start"] <= T.PARAGRAPH_MAX for p1, p2 in zip(ps, ps[1:]))
    assert len(ps) == 3


def test_parrafos_respetan_capitulos():
    chapters = [{"start_time": 0, "title": "A"}, {"start_time": 10, "title": "B"}]
    ps = T.paragraphs([seg(0, "uno"), seg(5, "dos"), seg(10, "tres")], chapters)
    assert [(p["chapter"], p["text"]) for p in ps] == [("A", "uno dos"), ("B", "tres")]
    r = T.render([seg(0, "uno"), seg(10, "tres")], "paragraphs", chapters)
    assert r == "### A\n\n[0:00] uno\n\n### B\n\n[0:10] tres"


def test_fmt_ts_con_horas():
    assert T.fmt_ts(3725) == "1:02:05" and T.fmt_ts(65.9) == "1:05"
