"""Machine-readable phase gates and remaining data priorities for new BRT design."""
import argparse,json
from pathlib import Path

def manifest(zones,od,candidates,turns,scored,robust,networks,config):
    n=len(candidates.get("features",[]))
    rows=[
      {"step":1,"name":"Zonas H3 8/9 y fuentes","status":"EXPLORATORIO",
       "evidence":{"h3_res8_cells":len(zones["zones"]),"h3_res9_required":True,
                   "full_urban_boundary_verified":False},
       "blockers":["OFFICIAL_COMPLETE_URBAN_BOUNDARY_NOT_VERIFIED"]},
      {"step":2,"name":"OD gravitacional y áreas puerta","status":"EXPLORATORIO",
       "evidence":{"scenarios":len(od["scenarios"]),"external_gateways_assumed":True,
                   "flow_units_observed":False},
       "blockers":["NO_CALIBRATED_OD","EXTERNAL_GATEWAY_COUNTS_NOT_OBSERVED"]},
      {"step":3,"name":"Grafo apto Yutong y huella barrida","status":"BLOQUEADO",
       "evidence":{"candidates_doubtful":turns["doubtful"],"certified_viable":turns["viable_confirmed"],
                   "turn_diameter_scenarios_m":config["vehicle"]["turning_diameter_scenarios_m"]},
       "blockers":["NO_CURB_EDGE_POLYGONS","NO_VERIFIED_BUS_SWEEP_OR_TERMINAL_TURNS",
                   "HEIGHT_GRADE_AND_OBSTACLES_UNVERIFIED"]},
      {"step":4,"name":"Generación independiente de rutas","status":"EXPLORATORIO" if n>=100 else "INCOMPLETO",
       "evidence":{"unique_auto_generated":n,
                   "no_legacy_candidates":all(x["properties"]["candidate_id"].startswith("AUTO-") for x in candidates["features"])},
       "blockers":["PHYSICAL_FILTER_CANNOT_APPROVE_CANDIDATES"]},
      {"step":5,"name":"Acceso peatonal y viajes capturados","status":"EXPLORATORIO",
       "evidence":{"candidates_scored":len(scored["ranked_candidates"]),
                   "walk_graph_method":"OSM pedestrian Dijkstra",
                   "trips_observed":False},
       "blockers":["STOP_PLACEMENT_NOT_CURB_VALIDATED","IN_VEHICLE_OD_DETOUR_APPROXIMATE",
                   "RETURN_CYCLE_HYPOTHETICAL","LOAD_FACTOR_CANNOT_CALIBRATE"]},
      {"step":6,"name":"Top 6 y robustez de ruta inicial","status":"EXPLORATORIO",
       "evidence":{"base_winner_id":robust["base_first_id"],
                   "tested_scenarios":robust["scenario_count"],
                   "operationally_recommended":False},
       "blockers":["TURN_VARIANT_ROBUSTNESS_UNVERIFIED","POI_WEIGHT_SENSITIVITY_NOT_COMPLETE",
                   "NO_PHYSICAL_APPROVAL"]},
      {"step":7,"name":"OD único y selección de red CP-SAT","status":"EXPLORATORIO" if networks["scenarios"] else "INCOMPLETO",
       "evidence":{"demand_levels":len(networks["scenarios"]),
                   "budgets":[10,20,30],"independent_and_progressive":True,
                   "operationally_approved":0},
       "blockers":["TRANSFERS_NOT_EXPLICITLY_MODELED_AS_OD",
                   "HUB_SAFETY_AND_WALKING_LINKS_UNVERIFIED",
                   "NETWORK_SOLVER_ONLY_TOP_CANDIDATES_OD_SUBSET"]},
      {"step":8,"name":"GTFS + r5py + aforos","status":"BLOQUEADO",
       "evidence":{"valid_operational_GTFS":False,"calibrated_r5py":False,
                   "observed_boardings":False},
       "blockers":["NO_APPROVED_STOPS","NO_PUBLISHED_OBSERVED_GTFS",
                   "NO_FIELD_CALIBRATION_OR_COUNTS","NO_APPROVED_BUS_GEOMETRY"]}
    ]
    gaps=[
      {"priority":1,"data":"Bordillos, medianas, radios y maniobras terminales","impact":"May invalidate every proposed route physically","status":"NOT_AVAILABLE"},
      {"priority":2,"data":"Conteos de pasajeros y OD / aforos","impact":"Trips and load factors cannot be treated as demand","status":"NOT_AVAILABLE"},
      {"priority":3,"data":"Horarios reales, congestión punta/valle por sentido","impact":"Fleet size and transfer waiting unreliable","status":"NOT_AVAILABLE"},
      {"priority":4,"data":"Cruces peatonales, barreras y puntos legales de parada","impact":"Transfer accessibility and stop placement unverified","status":"NOT_AVAILABLE"},
      {"priority":5,"data":"Perímetro completo validado y empleo efectivo","impact":"Study bbox and POI attractors may omit residents/jobs","status":"NOT_AVAILABLE"},
      {"priority":6,"data":"Alturas/pesos/pendientes y restricciones de giro OSM contrastadas","impact":"Mapped route may be forbidden or unsuitable","status":"NOT_AVAILABLE"}
    ]
    return {"status":"EXPLORATORY_NOT_APPROVED","design_version":"ALGORITHMIC_V2",
      "prior_route_ids_consumed":0,"historical_L1_used_as_seed":False,
      "vehicle":"Yutong ZK6126HG","physical_routes_approved":0,
      "initial_route_recommended_for_operation":None,
      "step_gates":rows,"missing_data_prioritized":gaps,
      "provenance":{"worldpop":config["sources"]["population"],
                    "overture":config["sources"]["attractions"],"osm":config["sources"]["roads"],
                    "synthetic_OD":"Gravity normalized with configurable category weights and exponents"},
      "warning":"A green CI proves computation and evidence gates, NOT suitability to operate buses."}

def main():
    p=argparse.ArgumentParser()
    for k in ("zones","od","candidates","turns","scored","robust","networks","config","output"):
        p.add_argument("--"+k,type=Path,required=True)
    a=p.parse_args()
    x=manifest(*(json.loads(getattr(a,k).read_text()) for k in
       ("zones","od","candidates","turns","scored","robust","networks","config")))
    a.output.write_text(json.dumps(x,ensure_ascii=False,indent=2))
    print(json.dumps({"status":x["status"],"steps":len(x["step_gates"]),
                      "approved":x["physical_routes_approved"],
                      "L1_seeded":x["historical_L1_used_as_seed"]}))
if __name__=="__main__":main()
