"""Explainable desk-screen ranking; never promotes hypothetical routes to operational approval."""
import argparse,json
from pathlib import Path

def rank(report):
    proposals=report.get("proposals") or []
    ranked=[]
    for p in proposals:
        checks=p.get("desktop_checks") or {}
        if p.get("desktop_status") not in ("DESKTOP_SCREEN_PASS_UNVALIDATED","DESKTOP_SCREEN_REVIEW_OR_REJECT"):
            raise ValueError("Missing desktop assessment evidence")
        resident=max(0,float(p.get("resident_coverage_proxy") or 0))
        dest=max(0,p["destinations"]["pois_reached_proxy"])
        transfers=len(p.get("transfer_links",[]))
        routes=len(p.get("selected_routes",[]))
        peaks=sum(v["peak_headway_over_target"] for v in p.get("peak_sensitivity",[]))
        # Heuristic not demand weights: population and destination counts have distinct units.
        score=round(100*resident/(resident+10000) + 5*min(dest,20)
                    + 10*min(transfers,6) - 15*len(p.get("isolated_routes",[])) - 12*peaks,2)
        ranked.append({"budget":p["budget"],"scenario":p["scenario"],
            "assumed_speed_kmh":p["assumed_speed_kmh"],
            "route_ids":[v["route"] for v in p["selected_routes"]],
            "proxy_score":score,"score_is_not_passenger_forecast":True,
            "desktop_status":p["desktop_status"],
            "operational_gate":p["operational_gate"],
            "residents_near_provisional_stops":resident,
            "mapped_pois_near_stops":dest,
            "provisional_transfer_links":transfers,
            "peak_headway_risks":peaks,
            "failed_desktop_checks":[key for key,val in checks.items() if not val]})
    grouped={}
    for r in ranked:
        key=(r["budget"],r["scenario"])
        grouped.setdefault(key,[]).append(r)
    comparisons=[]
    for (budget,arm),items in sorted(grouped.items()):
        items.sort(key=lambda r:(r["desktop_status"]!="DESKTOP_SCREEN_PASS_UNVALIDATED",
                                 -r["proxy_score"],r["assumed_speed_kmh"]))
        comparisons.append({"budget":budget,"l1_arm":arm,
            "desktop_survivors":[r for r in items if r["desktop_status"]=="DESKTOP_SCREEN_PASS_UNVALIDATED"],
            "all_proposals_ranked":items,
            "operationally_approved":0})
    return {"status":"HEURISTIC_SCREENED_NOT_ROUTING_OPTIMUM",
       "metric_definition":"100*residents/(residents+10000)+5*min(POIs,20)+10*min(transfer_links,6)-15*isolated_routes-12*peak_headway_risks",
       "comparisons":comparisons,"operationally_approved":0,
       "warning":"This is post-hoc ranking of population-optimized solutions, NOT multiobjective CP-SAT or true passenger OD/travel-time maximization."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    result=rank(json.loads(a.input.read_text()))
    a.output.write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print(json.dumps({"comparison_groups":len(result["comparisons"]),
                      "desktop_survivors":sum(len(x["desktop_survivors"]) for x in result["comparisons"])}))
if __name__=="__main__":main()
