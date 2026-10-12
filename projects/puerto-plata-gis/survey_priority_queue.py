"""Prioritize inspections around candidate turn risks without certifying routes.

Waypoint bends are not street-level turns. Transects are not measured widths.
The output is a field/imagery acquisition work queue, NOT bus roadworthiness.
"""
from __future__ import annotations
import argparse
import json
import math
from collections import Counter
from pathlib import Path

ROUTES_10_BUS = ("C00-09", "C00-10", "C02-04")
METRES_PER_DEG = 111195.0


def distance_m(lon1, lat1, lon2, lat2):
    """Sufficiently accurate approximation for local *prioritization*, not surveying."""
    lat = math.radians((lat1 + lat2) / 2.0)
    return METRES_PER_DEG * math.hypot(
        (lon1 - lon2) * math.cos(lat), lat1 - lat2
    )


def inspect_queue(turn_report, profiles_fc, radius_m=90.0, max_profiles=12):
    if not (0 < radius_m <= 2000):
        raise ValueError("Invalid inspection radius")
    if not isinstance(max_profiles, int) or not (1 <= max_profiles <= 1000):
        raise ValueError("Invalid max_profiles")
    if turn_report.get("status") != "EXPLORATORIO_SIN_APROBACION_FISICA":
        raise ValueError("Expected unapproved turn-risk evidence")

    transects = []
    for profile in profiles_fc.get("features", []):
        coords = profile.get("geometry", {}).get("coordinates", [])
        properties = profile.get("properties") or {}
        if profile.get("geometry", {}).get("type") != "LineString" or len(coords) != 2:
            continue
        if properties.get("status") != "INSPECTION_TRANSECT_NOT_MEASURED":
            # Prioritized subsets retain status under this exact key.
            continue
        x = (coords[0][0] + coords[1][0]) / 2
        y = (coords[0][1] + coords[1][1]) / 2
        transects.append((x, y, properties.get("segment_id"), coords))

    tasks = []
    route_counts = Counter()
    for turn in turn_report.get("risks", []):
        route = turn.get("candidate")
        if route not in ROUTES_10_BUS:
            continue
        try:
            x = float(turn["longitude"])
            y = float(turn["latitude"])
            angle = float(turn["heading_change_deg"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError("Malformed turn-risk record") from e
        if not all(math.isfinite(z) for z in (x, y, angle)):
            raise ValueError("Non-finite turn-risk coordinate")
        nearest = []
        for tx, ty, segment_id, coords in transects:
            d = distance_m(x, y, tx, ty)
            if d <= radius_m:
                nearest.append((round(d, 2), str(segment_id), coords))
        nearest.sort(key=lambda row: (row[0], row[1]))
        shortlisted = nearest[:max_profiles]
        task = {
            "candidate": route,
            "latitude": y,
            "longitude": x,
            "heading_change_deg": angle,
            "nearby_unmeasured_profiles": len(nearest),
            "profile_samples": [
                {"distance_from_waypoint_m": d,
                 "segment_id": segment,
                 "geometry": {"type": "LineString", "coordinates": coords}}
                for d, segment, coords in shortlisted
            ],
            "vehicle": "Yutong ZK6126HG",
            "priority": "FIELD_REVIEW",
            "road_width_status": "UNKNOWN",
            "physical_turn_status": "NOT_ASSESSED",
            "required_evidence": [
                "Measured clear carriageway and curb polygons",
                "Median opening and roadside obstacles",
                "License-cleared imagery or field survey",
                "Vehicle-specific full swept-path template",
            ],
        }
        tasks.append(task)
        route_counts[route] += 1

    tasks.sort(key=lambda t: (
        -t["heading_change_deg"], t["candidate"], t["latitude"], t["longitude"]))
    return {
        "status": "UNVERIFIED_FIELD_SURVEY_QUEUE",
        "vehicle": "Yutong ZK6126HG",
        "turning_circle_variant_reference_m": 20.5,
        "max_nearby_profile_distance_m": radius_m,
        "total_tasks": len(tasks),
        "tasks_by_route": {key: route_counts[key] for key in ROUTES_10_BUS},
        "street_widths_measured": 0,
        "maneuvers_approved": 0,
        "risks": tasks,
        "limitations": [
            "Only GIS waypoint deflections, not actual driving turns",
            "Nearby OSM edges may not be on the candidate route",
            "Transect positions do not locate true curb edges",
            "Unknown is not geometrically feasible",
        ],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--turns", type=Path, required=True)
    p.add_argument("--transects", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    turns = json.loads(a.turns.read_text(encoding="utf8"))
    sections = json.loads(a.transects.read_text(encoding="utf8"))
    report = inspect_queue(turns, sections)
    a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"status": report["status"], "tasks": report["total_tasks"],
                      "tasks_by_route": report["tasks_by_route"]}))


if __name__ == "__main__":
    main()
