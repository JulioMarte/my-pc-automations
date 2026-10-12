"""Execute multiobjective nested CP-SAT on real WorldPop/OSM/Overture proxies."""
import argparse,json
from pathlib import Path
import osmnx as ox
from run_exploratory_curve import cycles_for_scenario
from prepare_optimization_input import build
from mobility_multicriteria_cp_sat import optimize

def compute(root,speeds=(12,18,24),budgets=(10,20,30)):
    features=json.loads((root/"discovered_routes.geojson").read_text())["features"]
    competition=json.loads((root/"route_competition.json").read_text())
    l1=json.loads((root/"initial_route.geojson").read_text())
    pop=json.loads((root/"population.json").read_text())["cells"]
    poi=json.loads((root/"destinations.geojson").read_text())["features"]
    cfg=json.loads((root/"study_config.json").read_text())
    graph=ox.load_graphml(root/"walk.graphml")
    stopmap={f["properties"]["id"]:f["geometry"]["coordinates"] for f in features}
    results=[]
    for speed in speeds:
        cycles,_=cycles_for_scenario(features,competition,l1,speed)
        data=build(graph,pop,features,cycles)
        args={"routes":data["routes"],"cells":data["cells"],"stopmap":stopmap,"pois":poi,
              "budgets":budgets,"headways":cfg["transit"]["allowed_headways_minutes"],
              "reserve":cfg["transit"]["reserve_ratio"]}
        results.append({"assumed_speed_kmh":speed,
              "with_l1":optimize(**args,l1_required=True),
              "without_l1_constraint":optimize(**args,l1_required=False)})
    return {"status":"MULTIOBJECTIVE_PHASED_HYPOTHESIS_NOT_OPERATIONALLY_APPROVED",
        "results":results,"physical_routes_approved":0,
        "demand_calibrated":False,"traffic_calibrated":False,
        "note":"Nested 10/20/30 selections have POI/transfer/peak proxy objective; no verified stop accessibility or physical bus clearance."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,default=Path(__file__).resolve().parent)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    x=compute(a.root)
    out=a.output or a.root/"multicriteria_nested_fleet.json"
    out.write_text(json.dumps(x,indent=2,ensure_ascii=False))
    print(json.dumps({"speed_scenarios":len(x["results"]),
                      "solved_budget_options":sum(sum(b.get("status") in ("OPTIMAL","FEASIBLE_NOT_PROVEN_OPTIMAL") for b in arm["budgets"]) for s in x["results"] for arm in (s["with_l1"],s["without_l1_constraint"]))}))
if __name__=="__main__":main()
