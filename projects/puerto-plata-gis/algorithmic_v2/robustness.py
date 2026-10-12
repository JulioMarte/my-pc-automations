"""Top-six initial corridor and scenario stability; NOT a bus recommendation."""
import argparse,json
from pathlib import Path
def analyze(scored,config):
    rows=scored["ranked_candidates"]
    if not rows:raise ValueError("No candidate ranking")
    speeds=config["service"]["speed_kmh_scenarios"]
    scenario_names=sorted({sc["scenario"] for r in rows for sc in r["od_scores"]})
    appearances={r["candidate_id"]:0 for r in rows}
    first_places={r["candidate_id"]:0 for r in rows}
    comparisons=[]
    for od_name in scenario_names:
        for speed in speeds:
            rank=[]
            for r in rows:
                demand=next(x["relative_od_units_accessible_proxy"] for x in r["od_scores"] if x["scenario"]==od_name)
                service=[s for s in r["service_scenarios"] if s["speed_kmh_assumed"]==speed
                         and s["headway_minutes"]==15 and s["reserve_ratio_assumed"]==0.15]
                if len(service)!=1:raise ValueError("Scenario mismatch")
                fleet=service[0]["fleet_buses_proxy"]
                rank.append((demand/fleet,demand,r["candidate_id"]))
            rank.sort(reverse=True)
            top=rank[:6]
            for _,_,id in top:appearances[id]+=1
            if top:first_places[top[0][2]]+=1
            comparisons.append({"od_scenario":od_name,"speed_assumed_kmh":speed,
                               "top6":[{"candidate_id":id,"relative_od_per_bus":round(value,5)}
                                       for value,_,id in top],
                               "physical_gates_passed":False})
    summary=sorted(({"candidate_id":id,"top6_occurrences":n,
                      "top6_share":round(n/len(comparisons),3),
                      "first_place_occurrences":first_places[id]}
                     for id,n in appearances.items()),key=lambda x:(-x["top6_occurrences"],-x["first_place_occurrences"],x["candidate_id"]))
    winner=scored["top6"][0]["candidate_id"]
    return {"status":"HYPOTHETICAL_INITIAL_ROUTE_ROBUSTNESS_UNCERTIFIED",
        "base_top6":scored["top6"],"base_first_id":winner,
        "base_first_top6_share":next(x["top6_share"] for x in summary if x["candidate_id"]==winner),
        "scenario_comparisons":comparisons,"robust_candidate_occurrences":summary[:20],
        "scenario_count":len(comparisons),"operationally_recommended_route":None,
        "stability_tested":{"gravity_scenarios":True,"speed_scenarios":True,
                           "turn_diameters":False,"attraction_weight_perturbation":False,
                           "field_measured_demand":False},
        "reason_no_recommendation":"Unverified turn swept paths, uncertain OD weights, uncalibrated demand and speculative bus cycle."}

def main():
    p=argparse.ArgumentParser()
    for n in ("scored","config","output"):p.add_argument("--"+n,type=Path,required=True)
    a=p.parse_args()
    r=analyze(json.loads(a.scored.read_text()),json.loads(a.config.read_text()))
    a.output.write_text(json.dumps(r,separators=(",",":")))
    print(json.dumps({"base_first":r["base_first_id"],"scenario_count":r["scenario_count"],
                      "base_first_top6_share":r["base_first_top6_share"],"operational_recommendation":None}))
if __name__=="__main__":main()
