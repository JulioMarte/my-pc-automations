"""Compare Valhalla terminal shortcuts against waypoint-constrained candidates.

The multi-point sequence is provisional; this tool compares network evidence,
not operational feasibility. It refuses a numerical conclusion on failed legs.
"""
import argparse,json
from pathlib import Path

def compare(direct,via):
    direct_index={r["id"]:r for r in direct.get("routes",[])}
    rows=[]
    for r in via.get("routes",[]):
        base=direct_index.get(r["id"])
        if base is None:raise ValueError("No direct-route evidence for "+r["id"])
        outbound=base.get("outbound") or {}
        inbound=base.get("inbound") or {}
        values=[outbound.get("distance_km"),inbound.get("distance_km")]
        if not all(isinstance(v,(int,float)) and v>0 for v in values):
            raise ValueError("Missing valid directional distance for "+r["id"])
        original=sum(values)
        success=r.get("complete_routable_sequence") and r.get("failed_segments")==0
        constrained=r.get("sum_segment_distance_km") if success else None
        rows.append({"candidate":r["id"],"terminal_pair_round_trip_km":round(original,3),
                     "waypoint_sequence_km":constrained,
                     "difference_km":round(constrained-original,3) if constrained is not None else None,
                     "constraint_sequence_complete":bool(success),
                     "stop_order_verified":False,"operational_approval":False,
                     "interpretation":"Paths cover different routing requirements; differences are not error margins"})
    return {"status":"EXPLORATORY_ROUTE_LENGTH_COMPARISON","routes":rows,
            "total_compared":len(rows),"maneuvers_approved":0,
            "limitations":["Terminal-pair outbound+inbound is not identical to full ordered waypoint sequence",
                           "Waypoint order may already encode an entire out-and-back loop",
                           "No physically certified terminal return or passenger demand calibration"]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--direct",type=Path,required=True)
    p.add_argument("--via",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    x=compare(json.loads(a.direct.read_text()),json.loads(a.via.read_text()))
    a.output.write_text(json.dumps(x,indent=2))
    print(json.dumps({"status":x["status"],"routes":x["routes"]}))
if __name__=="__main__":main()
