"""Machine-readable milestone gates for unbiased Puerto Plata BRT redesign.

Never converts provisional geometric or synthetic OD success into
APPROVED vehicle routes or a fleet recommendation.
"""
import argparse,json
from pathlib import Path

def manifest(zones,od,candidates,physical,scored=None):
    count=candidates["candidate_count"]
    has_scores=scored is not None and len(scored.get("candidate_scores",[]))==count
    top=([{"rank_for_review":i+1,"candidate":r["candidate"],"methods":r["methods"],
           "hypothetical_od_capture":r["captured_od_trips_hypothetical_base"],
           "stop_count":r["stop_count"],
           "max_trips_per_fleet_bus_hypothesis":max((case["hypothetical_od_trips_per_fleet_bus"] for case in r["hypothetical_fleet_cases"]),default=0),
           "recommendation":"BLOQUEADO"} for i,r in enumerate(scored["candidate_scores"][:6])]
         if has_scores else [])
    ranked=sorted(candidates["candidates"],key=lambda x:-x["source_demand_proxy"])
    steps=[
      {"step":1,"name":"Zonas H3","status":"EXPLORATORIO_GENERADO",
       "evidence":{"h3_8":len(zones["h3_cells"]["8"]),"h3_9":len(zones["h3_cells"]["9"])},
       "blockers":["URBAN_BOUNDARY_NOT_VERIFIED","WORLDPOP_NOT_OBSERVED"]},
      {"step":2,"name":"OD gravitacional","status":"EXPLORATORIO_GENERADO",
       "evidence":{"scenarios":len(od["experiments"]),"top20":od["experiments"][0]["top_20_cells_by_through_flow"]},
       "blockers":["NO_INDEPENDENT_DEMAND_CALIBRATION","EXTERNAL_GATEWAYS_ASSUMED"]},
      {"step":3,"name":"Red físicamente apta","status":"BLOQUEADO",
       "evidence":{"tested":physical["audited"],"viable":physical["VIABLE"],"doubtful":physical["DUDOSO"],"inviable":physical["INVIABLE"]},
       "blockers":["NO_CURB_BOUNDS","SWEPT_PATH_NOT_VALIDATED","OSM_TURN_RESTRICTIONS_NOT_AUDITED"]},
      {"step":4,"name":"Candidatas sin sesgo de rutas anteriores","status":"EXPLORATORIO_GENERADO",
       "evidence":{"generated":count,"target_met":candidates["target_met"],
                   "methods":sorted({m for r in ranked for m in r["methods"]})},
       "blockers":["RETURN_TERMINALS_UNVERIFIED","BUS_WIDTH_CLEARANCE_UNKNOWN"]},
      {"step":5,"name":"Captura OD y paradas algorítmicas","status":"EXPLORATORIO_GENERADO" if has_scores else "BLOQUEADO_NO_EJECUTADO",
       "evidence":{"scored":len(scored["candidate_scores"]) if has_scores else 0},
       "blockers":["ONE_WAY_FRAGMENT_ONLY","STOP_SAFETY_NOT_VERIFIED","NO_TRAFFIC_CALIBRATION"]},
      {"step":6,"name":"Ruta inicial y robustez","status":"BLOQUEADO",
       "evidence":{"top6_review_only":top},
       "blockers":["ALL_CANDIDATES_PHYSICALLY_DOUBTFUL","ROBUSTNESS_MATRIX_NOT_COMPLETED"]},
      {"step":7,"name":"CP-SAT viaje único y flotas 10/20/30","status":"BLOQUEADO_NO_EJECUTADO",
       "evidence":{"operationally_valid_candidates":physical["VIABLE"]},
       "blockers":["NO_OD_CAPTURE_MATRIX_FOR_NETWORK","TRANSFER_WALK_TRAVEL_NOT_VERIFIED","ALL_TURNS_DOUBTFUL"]},
      {"step":8,"name":"GTFS r5py y calibración","status":"BLOQUEADO_NO_EJECUTADO",
       "evidence":{"aforos_observados":False,"gtfs_validated":False},
       "blockers":["NO_APPROVED_ROUTE_ALIGNMENT","NO_MEASURED_COUNTS","NO_OPERATIONAL_GTFS"]},
    ]
    missing=[
      {"priority":1,"field":"curb_to_curb widths, turning restriction and bus swept path geometry","impact":"Cannot approve a single bus route, turnaround, or stop"},
      {"priority":2,"field":"origin-destination counts / INTRANT DGTT / independent sample","impact":"Cannot calibrate OD totals or modal share"},
      {"priority":3,"field":"peak directional commercial speeds and delays","impact":"Cannot certify 10/15/20 headways or fleet requirements"},
      {"priority":4,"field":"OSM walk-route crossing, step-free stop and platform evidence","impact":"Cannot certify transfers and realistic walk access"},
      {"priority":5,"field":"urban footprint and external gateway counts","impact":"Cannot confirm full municipal coverage or external corridor demand"},
      {"priority":6,"field":"employment and attraction category validation","impact":"Mapped POIs do not proxy actual workplaces reliably"}
    ]
    return {"status":"OD_FIRST_STUDY_PARTIAL_HARD_GATES_ACTIVE","steps":steps,
       "recommended_initial_route":None,"ranked_candidates_for_review":top,
       "network_10_20_30_status":"BLOQUEADO_NO_EJECUTADO",
       "operationally_approved_routes":0,"fleet_purchase_recommended":False,
       "missing_data_by_impact":missing,
       "provenance_by_field":{
        "worldpop_residents_estimated":"WorldPop 2025 pixel-centroid assignment to H3; satellite model",
        "poi_weight_proxy":"Overture POI mapped tags multiplied by od_first_config.json category weights",
        "hypothetical_trips_per_day":"gravity beta and daily trip propensity parameters in config",
        "source_demand_proxy":"sum of synthetic OD lines supporting directed OSM paths, NOT captured riders",
        "theoretical_rigid_body_envelope_area_m2":"Shapely union of rigid rectangles on OSM centerline, not true steering swept area",
        "hypothetical_cycle_min":"doubled one-way road length/assumed speed + unsurveyed dwell/signals/recovery",
        "top6_review_only":"ranked on hypothetical trips per bus; no physical approval"}}

def main():
    p=argparse.ArgumentParser()
    for n in ("zones","od","candidates","physical","output"):p.add_argument("--"+n,type=Path,required=True)
    p.add_argument("--scored",type=Path)
    a=p.parse_args()
    read=lambda x:json.loads(x.read_text())
    out=manifest(read(a.zones),read(a.od),read(a.candidates),read(a.physical),
                 read(a.scored) if a.scored and a.scored.exists() else None)
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps({"steps":len(out["steps"]),"status":out["status"],
                      "recommended":out["recommended_initial_route"]}))
if __name__=="__main__":main()
