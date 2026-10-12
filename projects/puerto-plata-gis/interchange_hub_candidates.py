"""Identify provisional bus interchange hubs in evaluated route proposals.

Uses distance-only transfer proxies; no footpath, crossings, platforms,
land availability, observed dwell, synchronization or physical approval.
"""
import argparse,json,math
from pathlib import Path
M=111195.0
def distance(a,b):
    lat=math.radians((a[1]+b[1])/2)
    return M*math.hypot((a[0]-b[0])*math.cos(lat),a[1]-b[1])

def hubs(report,merge_radius_m=300):
    output=[]
    for proposal in report.get("proposals",[]):
        candidates=[]
        for link in proposal.get("transfer_links",[]):
            a=link["lonlat_a"]; b=link["lonlat_b"]
            midpoint=[(a[0]+b[0])/2,(a[1]+b[1])/2]
            matched=None
            for entry in candidates:
                if distance(midpoint,entry["center_lonlat"])<=merge_radius_m:
                    matched=entry;break
            if matched is None:
                matched={"center_lonlat":midpoint,"route_ids":set(),
                    "transfer_pairs":0,"transfer_walk_distances_m":[],
                    "random_arrival_wait_minutes":[]}
                candidates.append(matched)
            matched["route_ids"].update((link["route_a"],link["route_b"]))
            matched["transfer_pairs"]+=1
            matched["transfer_walk_distances_m"].append(link["transfer_walk_m_straight_line"])
            matched["random_arrival_wait_minutes"].append(link["expected_wait_minutes_if_random_arrival"])
        ordered=[]
        for i,h in enumerate(candidates,1):
            max_wait=max(h["random_arrival_wait_minutes"])
            ordered.append({"candidate_hub_id":f"H{i:02}",
                "approx_center_lonlat":h["center_lonlat"],
                "connecting_routes":sorted(h["route_ids"]),
                "connecting_route_count":len(h["route_ids"]),
                "route_pair_count":h["transfer_pairs"],
                "shortest_straight_line_walk_m":min(h["transfer_walk_distances_m"]),
                "longest_straight_line_walk_m":max(h["transfer_walk_distances_m"]),
                "max_random_arrival_wait_min_proxy":max_wait,
                "possible_pulse_coordination":len(h["route_ids"])>1,
                "accessibility_verified":False,"physical_hub_approved":False})
        ordered.sort(key=lambda v:(-v["connecting_route_count"],-v["route_pair_count"],
                                   v["max_random_arrival_wait_min_proxy"],v["approx_center_lonlat"]))
        output.append({"budget":proposal["budget"],"scenario":proposal["scenario"],
           "assumed_speed_kmh":proposal["assumed_speed_kmh"],
           "interchange_candidates":ordered,"interchange_approval":False,
           "recommended_schedule_action":"TEST_TIMED_PULSE_OFFSETS_ONLY_AFTER_TRAVEL_TIME_NETWORK_VALIDATION"})
    return {"status":"PROVISIONAL_INTERCHANGE_HUBS_NOT_APPROVED",
        "evaluated_networks":len(output),"networks":output,"approved_hubs":0,
        "method":"Cluster transfer candidate midpoints within 300 m; count distinct lines and approximate waits",
        "limitations":["Hub positions are approximate geometric midpoints, not surveyed platform locations",
                       "Straight-line separation ignores barriers and road crossings",
                       "Random-arrival headway/2 is not scheduled transfer waiting",
                       "Timetable coordination needs direction-specific travel time and variability"]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    x=hubs(json.loads(a.input.read_text()))
    a.output.write_text(json.dumps(x,ensure_ascii=False,indent=2))
    print(json.dumps({"networks":x["evaluated_networks"],
                      "total_candidate_hubs":sum(len(v["interchange_candidates"]) for v in x["networks"])}))
if __name__=="__main__":main()
