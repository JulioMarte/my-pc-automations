"""Gate route cycles before using waypoint path length in fleet optimization.

Ordered waypoint paths are neither a round-trip schedule nor validated stops.
A near-closed endpoint does not prove a legal or feasible turnaround.
"""
import argparse,json
from pathlib import Path

def audit(data, tolerance_m=30):
    rows=[]
    for r in data.get("routes",[]):
        e=r.get("endpoints") or {}
        complete=bool(r.get("complete_routable_sequence"))
        closure=e.get("distance_between_ends_m")
        geometrically_closed=bool(isinstance(closure,(int,float)) and closure<=tolerance_m)
        reasons=[]
        if not complete:reasons.append("ONE_OR_MORE_WAYPOINT_LEGS_FAILED")
        if not geometrically_closed:reasons.append("CYCLE_ENDPOINTS_NOT_CLOSED")
        reasons+=["RETURN_AND_TERMINAL_MANEUVER_NOT_VALIDATED","DWELL_LAYOVER_NOT_OBSERVED",
                  "ROUTE_STOPS_NOT_CERTIFIED"]
        rows.append({"candidate":r["id"],"waypoint_route_complete":complete,
                     "geometrically_closed":geometrically_closed,
                     "endpoints_separation_m":closure,
                     "waypoint_distance_km":r.get("sum_segment_distance_km"),
                     "vehicle_cycle_validated":False,"eligible_as_measured_cycle":False,
                     "blockers":reasons})
    return {"status":"WAYPOINT_PATHS_NOT_MEASURED_SERVICE_CYCLES",
            "routes_examined":len(rows),"approved_as_measured_cycles":0,
            "routes":rows,
            "optimization_policy":"Retain hypothetical speed/dwell sensitivity; do not substitute waypoint path as a measured round trip."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    x=audit(json.loads(a.input.read_text()))
    a.output.write_text(json.dumps(x,indent=2,ensure_ascii=False))
    print(json.dumps({"status":x["status"],"routes":x["routes_examined"],"approved":x["approved_as_measured_cycles"]}))
if __name__=="__main__":main()
