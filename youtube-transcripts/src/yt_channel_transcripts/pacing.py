"""Cliente respetuoso con YouTube: ritmo, presupuesto horario y pausa tras un bloqueo.

Por que existe: sin API key se usan las paginas publicas de YouTube, que limitan por IP.
Lo que dispara los bloqueos es el VOLUMEN y la persistencia tras un aviso, no "parecer
humano". Este modulo hace tres cosas, con estado compartido entre procesos (un archivo por
maquina, porque el limite es de la IP, no de la carpeta de datos):

1. Ritmo: intervalo minimo con variacion aleatoria entre peticiones de la misma clase.
2. Presupuesto: maximo de peticiones por hora por clase; al llegar, se detiene (no espera
   horas dentro de una llamada) y dice cuando se puede seguir.
3. Pausa tras bloqueo (circuit breaker): ante un 429/IpBlocked/"Sign in to confirm" se
   deja de pedir por completo durante un tiempo que se duplica con cada bloqueo seguido
   (1 h, 2 h, 4 h... hasta 24 h). Insistir durante un bloqueo lo alarga.

Valores por defecto basados en la guia de yt-dlp (sesion sin cuenta: ~300 videos/hora,
~1000 peticiones de pagina/hora; 5-10 s entre descargas) y en lo observado en este
proyecto (bloqueo de transcripciones tras ~20 seguidas). Configurables por entorno.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable

# clase -> (intervalo minimo s, intervalo maximo s, presupuesto por hora)
DEFAULTS: dict[str, tuple[float, float, int]] = {
    "page": (3.0, 6.0, 250),         # listado, metadatos, busqueda (cada uno son 1-3 peticiones reales)
    "transcript": (12.0, 25.0, 90),  # endpoint de subtitulos: el mas sensible
}
BASE_COOLDOWN = 3600.0
MAX_COOLDOWN = 24 * 3600.0
STRIKE_RESET = 24 * 3600.0  # sin bloqueos en 24 h, la escalada vuelve a empezar


class PausedError(Exception):
    """Base de las pausas preventivas (se convierte en BlockedError en core)."""

    def __init__(self, message: str, until: float):
        super().__init__(message)
        self.until = until


def _fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def state_path() -> Path:
    env = os.environ.get("YT_PACING_FILE")
    return Path(env).expanduser() if env else Path.home() / ".yt-channel-transcripts" / "pacing.json"


def _env_cfg(cat: str) -> tuple[float, float, int]:
    lo, hi, budget = DEFAULTS[cat]
    pre = f"YT_{cat.upper()}_"
    return (float(os.environ.get(pre + "MIN_SECONDS", lo)), float(os.environ.get(pre + "MAX_SECONDS", hi)),
            int(os.environ.get(pre + "PER_HOUR", budget)))


class Pacer:
    def __init__(self, path: Path | None = None, *, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None):
        self.path = Path(path) if path else state_path()
        self.clock, self.sleep = clock, sleep
        self.rng = rng or random.Random()
        self.lock = threading.Lock()

    # --- estado en disco -------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}

    def _save(self, st: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def _cat(st: dict[str, Any], cat: str) -> dict[str, Any]:
        return st.setdefault(cat, {"log": [], "last": 0.0, "cooldown_until": 0.0, "strikes": 0, "last_block": 0.0})

    # --- API ---------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        st, now = self._load(), self.clock()
        out = {}
        for cat in DEFAULTS:
            c = self._cat(st, cat)
            lo, hi, budget = _env_cfg(cat)
            used = sum(1 for t in c["log"] if now - t < 3600)
            out[cat] = {"used_last_hour": used, "budget_per_hour": budget, "interval_seconds": [lo, hi],
                        "paused_until": _fmt(c["cooldown_until"]) if c["cooldown_until"] > now else None,
                        "consecutive_blocks": c["strikes"]}
        return out

    def before(self, cat: str) -> None:
        """Comprueba pausa y presupuesto y espera el intervalo. Lanza PausedError sin hacer
        ninguna peticion si no se puede seguir."""
        lo, hi, budget = _env_cfg(cat)
        with self.lock:
            st = self._load()
            now = self.clock()
            # un bloqueo de paginas tambien frena los subtitulos (es una senal mas fuerte)
            for k in ([cat, "page"] if cat != "page" else [cat]):
                c = self._cat(st, k)
                if c["cooldown_until"] > now:
                    raise PausedError(
                        f"Pausa preventiva hasta {_fmt(c['cooldown_until'])}: YouTube limito esta IP "
                        f"({c['strikes']} bloqueo/s seguidos). No se hizo ninguna peticion.", c["cooldown_until"])
            c = self._cat(st, cat)
            c["log"] = [t for t in c["log"] if now - t < 3600]
            if len(c["log"]) >= budget:
                until = c["log"][0] + 3600
                raise PausedError(f"Presupuesto de {budget} peticiones/hora ({cat}) alcanzado; se puede seguir "
                                  f"a partir de {_fmt(until)}. Lo descargado queda guardado.", until)
            wait = c["last"] + self.rng.uniform(lo, hi) - now
            if wait > 0:
                self.sleep(wait)
                now = self.clock()
            c["last"] = now
            c["log"].append(now)
            if c["last_block"] and now - c["last_block"] > STRIKE_RESET:
                c["strikes"] = 0
            self._save(st)

    def blocked(self, cat: str) -> float:
        """Registra un bloqueo y activa la pausa escalonada. Devuelve hasta cuando."""
        with self.lock:
            st = self._load()
            now = self.clock()
            c = self._cat(st, cat)
            c["strikes"] = int(c["strikes"]) + 1
            c["last_block"] = now
            c["cooldown_until"] = now + min(MAX_COOLDOWN, BASE_COOLDOWN * 2 ** (c["strikes"] - 1))
            self._save(st)
            return c["cooldown_until"]

    def reset(self) -> None:
        """Borra pausas y contadores (por ejemplo, tras cambiar de red)."""
        with self.lock:
            self._save({})


_PACER: Pacer | None = None


def get_pacer() -> Pacer:
    global _PACER
    if _PACER is None or _PACER.path != state_path():
        _PACER = Pacer()
    return _PACER


def paced(cat: str, blocked_exc: type[BaseException], paused_factory: Callable[[PausedError], BaseException]):
    """Decorador para los adaptadores de red reales. `blocked_exc` es la excepcion de
    bloqueo del proyecto; `paused_factory` convierte una pausa en esa excepcion."""
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            p = get_pacer()
            try:
                p.before(cat)
            except PausedError as exc:
                raise paused_factory(exc) from exc
            try:
                return fn(*args, **kwargs)
            except blocked_exc:
                until = p.blocked(cat)
                raise blocked_exc(f"YouTube limito esta IP; pausa automatica hasta {_fmt(until)}. "
                                  "Lo descargado queda guardado.")
        return wrapper
    return deco
