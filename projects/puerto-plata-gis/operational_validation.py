"""Auditoria exploratoria de vehiculos y tiempos de ciclo. No certifica rutas."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

VEHICLES = {
    "yutong_zk6126hg": {"label": "Yutong ZK6126HG", "length_m": 12.17,
                 "body_width_m": 2.55, "mirror_width_m": None,
                 "turning_circle_m": 20.5, "turning_source": "yutong_kz_variant_reference_only",
                 "capacity_passengers": 90, "capacity_variants": [90,95,100], "max_grade_percent": None},
    "midibus_8_9m": {"label": "Midibus urbano 8-9 m (clase, modelo pendiente)",
                     "length_m": None, "body_width_m": None, "mirror_width_m": None,
                     "turning_circle_m": None, "turning_source": "no_verificado",
                     "capacity_passengers": None, "max_grade_percent": None},
}


def cycle_minutes(driving_seconds, stops, dwell_seconds=30,
                  signals_minutes=0, congestion_minutes=0, terminal_minutes=12):
    """Cada retraso se suma por separado. Nunca confundir manejo con ciclo."""
    quantities = (driving_seconds, stops, dwell_seconds, signals_minutes,
                  congestion_minutes, terminal_minutes)
    if any(not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in quantities):
        raise ValueError("Los tiempos y paradas deben ser finitos y no negativos")
    if int(stops) != stops:
        raise ValueError("stops debe ser entero")
    parts = {
        "driving_minutes": round(driving_seconds / 60, 3),
        "stop_dwell_minutes": round(stops * dwell_seconds / 60, 3),
        "signals_minutes": signals_minutes,
        "congestion_minutes": congestion_minutes,
        "terminal_minutes": terminal_minutes,
    }
    return {"components_minutes": parts,
            "cycle_minutes": round(driving_seconds / 60 + stops * dwell_seconds / 60
                                   + signals_minutes + congestion_minutes + terminal_minutes, 3),
            "calibration": "EXPLORATORIO_NO_MEDIDO"}


def assess_vehicle(vehicle, turns):
    """Sin barrido geométrico medido o evidencias de campo, no aprobar."""
    if any(vehicle.get(k) is None for k in
           ("length_m", "body_width_m", "mirror_width_m", "turning_circle_m",
            "capacity_passengers", "max_grade_percent")):
        verdict = "PENDIENTE_DE_VERIFICACION"
    else:
        verdict = "PENDIENTE_DE_VERIFICACION"
    issues = []
    for turn in turns:
        issues.append({
            "candidate": turn.get("candidate"), "point": turn.get("point"),
            "vehicle": vehicle["label"],
            "reason": "No existe simulacion del espacio barrido ni aprobacion en campo",
            "status": "PENDIENTE_DE_VERIFICACION",
        })
    return {"vehicle": vehicle, "status": verdict, "turns": issues,
            "missing_datasheet_fields": [k for k in ("length_m", "body_width_m",
             "mirror_width_m", "turning_circle_m", "capacity_passengers",
             "max_grade_percent") if vehicle.get(k) is None]}


def report_from_valhalla(evidence, stops_by_candidate=None):
    """Solo utiliza tiempos realmente presentes; no rellena rutas fallidas."""
    stops_by_candidate = stops_by_candidate or {}
    routes = ((evidence.get("routing") or {}).get("routes") or [])
    rows = []
    for r in routes:
        legs = [r.get("outbound"), r.get("inbound")]
        valid = all(isinstance(x, dict) and x.get("status") == "routed"
                    and isinstance(x.get("time_seconds"), (int, float))
                    and x["time_seconds"] > 0 for x in legs)
        row = {"candidate": r.get("id"), "routing": "APROBADO" if valid else "BLOQUEADO",
               "physical_turns": "PENDIENTE_DE_VERIFICACION",
               "operational_service": "EXPLORATORIO" if valid else "BLOQUEADO"}
        if valid:
            total = sum(x["time_seconds"] for x in legs)
            stop_count = stops_by_candidate.get(r.get("id"))
            if stop_count is None:
                row["cycle_status"] = "PENDIENTE_DE_VERIFICACION"
                row["cycle_reason"] = "Falta cantidad comprobable de paradas de ida y vuelta"
            else:
                row["cycle_scenarios"] = {
                    "optimista": cycle_minutes(total, stop_count, 20, 0, 0, 8),
                    "central": cycle_minutes(total, stop_count, 30, 6, 12, 12),
                    "pesimista": cycle_minutes(total, stop_count, 40, 12, 25, 18),
                }
                row["cycle_status"] = "EXPLORATORIO"
        rows.append(row)
    turns = [t for r in routes for t in r.get("turn_audit", [])]
    return {"status": "AUDITORIA_EXPLORATORIA_SIN_APROBACION_OPERATIVA",
            "valhalla_execution_status": evidence.get("status"),
            "vehicles": {name: assess_vehicle(vehicle, turns)
                         for name, vehicle in VEHICLES.items()},
            "routes": rows,
            "limitations": [
                "El circulo de giro no representa el espacio barrido por carroceria y espejos",
                "Pendientes, capacidad y geometria del midibus requieren ficha de modelo real",
                "Semaforos, congestion, paradas y terminales son supuestos exploratorios",
                "Una ruta digital no acredita seguridad vial, apertura de mediana ni operacion",
            ]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--valhalla-evidence", type=Path, required=True)
    p.add_argument("--stops-json", type=Path, help="Objeto route_id: cantidad total de paradas")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    raw = json.loads(a.valhalla_evidence.read_text(encoding="utf-8"))
    stops = json.loads(a.stops_json.read_text(encoding="utf-8")) if a.stops_json else {}
    result = report_from_valhalla(raw, stops)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "routes": len(result["routes"])}))


if __name__ == "__main__":
    main()
