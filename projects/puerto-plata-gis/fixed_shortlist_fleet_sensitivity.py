"""Uncalibrated fleet feasibility for the three selected graph loop scenarios.

Fixed route set and common headway; not an optimizer choosing routes, and
not an operationally approved capacity/schedule forecast.
"""
import argparse,json,math
from pathlib import Path

def compare(cycles, budgets=(10,20,30), headways=(10,15,20), reserve_ratio=0.15):
    rows=cycles.get("routes",[])
    if not rows:raise ValueError("No source cycles")
    if reserve_ratio<0 or reserve_ratio>=1:raise ValueError("Reserve out of bounds")
    if any(not r.get("fully_routable_graph_loop") for r in rows):
        return {"status":"BLOCKED_INCOMPLETE_GRAPH_LOOPS","fleet_calculated":False,
                "blocked":[r["candidate"] for r in rows if not r.get("fully_routable_graph_loop")],
                "operational_approval":False,"scenarios":[]}
    ids=[r["candidate"] for r in rows]
    if len(set(ids))!=len(ids):raise ValueError("Duplicate candidate cycles")
    template={(s["speed_kmh_assumed"],s["dwell_s_per_waypoint_assumed"],s["recovery_min_assumed"])
              for s in rows[0]["scenarios"]}
    if not template:raise ValueError("No scenario evidence")
    if any({(s["speed_kmh_assumed"],s["dwell_s_per_waypoint_assumed"],s["recovery_min_assumed"]) for s in r["scenarios"]}!=template for r in rows):
        raise ValueError("Incompatible scenario assumptions")
    scenarios=[]
    for speed,dwell,recovery in sorted(template):
        cycles_for={}
        for r in rows:
            found=next(s for s in r["scenarios"] if (s["speed_kmh_assumed"],s["dwell_s_per_waypoint_assumed"],s["recovery_min_assumed"])==(speed,dwell,recovery))
            cycles_for[r["candidate"]]=found["cycle_minutes_exploratory"]
        for headway in headways:
            if headway<=0:raise ValueError("Nonpositive headway")
            active={rid:math.ceil(minutes/headway) for rid,minutes in cycles_for.items()}
            active_total=sum(active.values())
            # Reserve vehicles calculated at aggregate fleet level, not per-line.
            fleet=math.ceil(active_total*(1+reserve_ratio))
            scenarios.append({"assumed_speed_kmh":speed,"assumed_dwell_s":dwell,
                "assumed_recovery_min":recovery,"headway_minutes":headway,
                "cycle_minutes_by_route":cycles_for,"active_buses_by_route":active,
                "active_total":active_total,"reserve_ratio":reserve_ratio,
                "fleet_with_reserve":fleet,
                "budgets":{str(b):{"within_budget":fleet<=b,
                                  "surplus_buses":b-fleet} for b in budgets},
                "physically_approved":False})
    return {"status":"EXPLORATORY_FIXED_THREE_ROUTE_FLEET_FEASIBILITY",
            "fleet_calculated":True,"operational_approval":False,
            "vehicle":"Yutong ZK6126HG","routes":ids,
            "budgets":list(budgets),"headways":list(headways),
            "scenarios":scenarios,
            "limitations":["Fixed shortlist only, no CP-SAT route selection",
                           "Valhalla graph continuity does not certify turnaround",
                           "Speeds, dwells and recovery times are uncalibrated assumptions",
                           "No measured demand, traffic, fleet reserve reliability or passenger capacity"]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    report=compare(json.loads(a.input.read_text()))
    a.output.write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(json.dumps({"status":report["status"],"scenario_count":len(report["scenarios"])}))
if __name__=="__main__":main()
