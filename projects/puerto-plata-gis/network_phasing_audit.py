"""Detect route continuity and change costs in 10 -> 20 -> 30 bus expansion.

Optimization budgets are independent; this audit does not invent a phased
optimization solution or assert infrastructure can be reused without surveys.
"""
import argparse,json
from pathlib import Path

def audit(report):
    scenarios=report.get("proposals") or []
    groups={}
    for p in scenarios:
        key=(p["assumed_speed_kmh"],p["scenario"])
        groups.setdefault(key,{})[p["budget"]]=p
    result=[]
    for (speed,arm),budgets in sorted(groups.items()):
        transitions=[]
        for prior,next_b in ((10,20),(20,30)):
            a=budgets.get(prior)
            b=budgets.get(next_b)
            if a is None or b is None:
                transitions.append({"from_budget":prior,"to_budget":next_b,"status":"MISSING_PHASE","lost":[],"added":[]})
                continue
            old={r["route"] for r in a["selected_routes"]}
            new={r["route"] for r in b["selected_routes"]}
            lost=sorted(old-new); added=sorted(new-old)
            transitions.append({"from_budget":prior,"to_budget":next_b,
                 "status":"NESTED_ROUTE_SET_UNVALIDATED" if not lost else "REPLACEMENT_NOT_STRAIGHT_EXPANSION",
                 "retained":sorted(old&new),"lost":lost,"added":added,
                 "route_retention_ratio":round(len(old&new)/len(old),3) if old else None,
                 "operationally_approved":False})
        result.append({"speed_kmh_assumed":speed,"scenario":arm,"transitions":transitions,
          "fully_nested_candidate_sequence":all(x["status"]=="NESTED_ROUTE_SET_UNVALIDATED" for x in transitions),
          "expansion_approved":False})
    return {"status":"INDEPENDENT_BUDGETS_NOT_PROVEN_PHASED_NETWORK",
        "scenario_groups":len(result),"groups":result,"phased_expansion_approved":0,
        "policy":"Do not describe 10/20/30 independent CP-SAT selections as incremental network expansion if routes are removed.",
        "next_implementation":"Nested multi-period optimization with stop/infrastructure retention and extension of route alignments."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    r=audit(json.loads(a.input.read_text()))
    a.output.write_text(json.dumps(r,indent=2,ensure_ascii=False))
    print(json.dumps({"scenario_groups":r["scenario_groups"],
                       "churn_transitions":sum(x["status"]=="REPLACEMENT_NOT_STRAIGHT_EXPANSION" for g in r["groups"] for x in g["transitions"])}))
if __name__=="__main__":main()
