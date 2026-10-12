"""Reproducible, fail-closed network assessment of CP-SAT proposals.

Uses provisional point stops and Overture POIs. Transfer feasibility and
peak performance are proxies, not measured travel or synchronized timetables.
No route with unresolved physical clearance can be operationally approved.
"""
import argparse,json,math
from pathlib import Path

M=111195.0
POI_WEIGHTS={"hospital":5,"health":5,"school":3,"education":3,"university":4,
             "commercial":2,"retail":2,"market":3,"government":3,"transport":5}

def metres(a,b):
    y=math.radians((a[1]+b[1])/2)
    return M*math.hypot((a[0]-b[0])*math.cos(y),a[1]-b[1])

def route_points(features):
    out={}
    for f in features:
        p=f.get("properties") or {}
        if f.get("geometry",{}).get("type")!="MultiPoint":continue
        key=p.get("id")
        if key:
            out[key]=f["geometry"]["coordinates"]
    return out

def destination_summary(stops,pois,radius=450):
    represented=set()
    weighted=0
    categories={}
    for i,f in enumerate(pois):
        geo=f.get("geometry") or {}
        if geo.get("type")!="Point":continue
        pt=geo.get("coordinates")
        if not pt or not stops:continue
        if min(metres(pt,s) for s in stops)>radius:continue
        represented.add(i)
        tag=str((f.get("properties") or {}).get("type","other")).lower()
        categories[tag]=categories.get(tag,0)+1
        weighted+=POI_WEIGHTS.get(tag,1)
    return {"pois_reached_proxy":len(represented),"destination_weight_proxy":weighted,
            "pois_by_type":categories,"poi_indices":sorted(represented)}

def transfers(selected,stops_by_route,max_walk=250):
    output=[]
    for i,left in enumerate(selected):
        for right in selected[i+1:]:
            a=stops_by_route.get(left["route"],[])
            b=stops_by_route.get(right["route"],[])
            pairs=[]
            for ia,p in enumerate(a):
                for ib,q in enumerate(b):
                    d=metres(p,q)
                    if d<=max_walk:pairs.append((round(d,1),ia,ib,p,q))
            pairs.sort()
            if pairs:
                best=pairs[0]
                output.append({"route_a":left["route"],"route_b":right["route"],
                               "transfer_walk_m_straight_line":best[0],
                               "stop_index_a":best[1],"stop_index_b":best[2],
                               "lonlat_a":best[3],"lonlat_b":best[4],
                               "transfer_walk_network_verified":False,
                               "expected_wait_minutes_if_random_arrival":round(right["headway_min"]/2,2),
                               "timed_transfer_verified":False})
    return output

def assess(fleet,features,poi_features,peak_slowdown=1.4):
    if peak_slowdown<1:raise ValueError("Peak slowdown must be >=1")
    points=route_points(features)
    outputs=[]
    for scenario in fleet.get("scenarios",[]):
        for arm in ("with_l1","without_l1_constraint"):
            for result in scenario.get(arm,[]):
                if result.get("status") not in ("OPTIMAL","FEASIBLE_NOT_PROVEN_OPTIMAL"):continue
                selected=result.get("selected",[])
                missing=[r["route"] for r in selected if not points.get(r["route"])]
                if missing:raise ValueError("No stop geometries: "+",".join(missing))
                all_stops=[p for r in selected for p in points[r["route"]]]
                ds=destination_summary(all_stops,poi_features)
                xfers=transfers(selected,points)
                active=set(r["route"] for r in selected)
                isolated=[r for r in active if not any(r in (x["route_a"],x["route_b"]) for x in xfers)]
                # Approximate peak headway recovery if actual cycle time rises, holding assigned fleet fixed.
                peak=[]
                for r in selected:
                    active_vehicles=(r.get("fleet") or {}).get("active")
                    cycle=r.get("cycle_min")
                    if not isinstance(active_vehicles,int) or active_vehicles<=0 or not isinstance(cycle,(float,int)) or cycle<=0:
                        raise ValueError("Missing route fleet or cycle")
                    projected=round(cycle*peak_slowdown/active_vehicles,2)
                    peak.append({"route":r["route"],"buses_active":active_vehicles,
                        "offpeak_headway_min":r["headway_min"],
                        "peak_headway_min_proxy":projected,
                        "peak_headway_over_target":projected>r["headway_min"],
                        "calibrated_with_traffic":False})
                reasons=[]
                if isolated and len(selected)>1:reasons.append("ISOLATED_ROUTE_TRANSFER_GRAPH")
                if not xfers and len(selected)>1:reasons.append("NO_PROVISIONAL_TRANSFER_POINTS")
                if any(p["peak_headway_over_target"] for p in peak):reasons.append("PEAK_HEADWAY_NOT_SUSTAINED_WITH_FIXED_FLEET")
                desktop_checks={
                    "has_residential_coverage_proxy":(result.get("covered_residents_estimate") or 0)>0,
                    "has_mapped_destination_access":ds["pois_reached_proxy"]>0,
                    "provisional_network_interchanges":not isolated if len(selected)>1 else True,
                    "peak_headways_hold_under_assumed_slowdown":not any(p["peak_headway_over_target"] for p in peak),
                    "has_route_selection":bool(selected)
                }
                desktop_status="DESKTOP_SCREEN_PASS_UNVALIDATED" if all(desktop_checks.values()) else "DESKTOP_SCREEN_REVIEW_OR_REJECT"
                reasons+=["PHYSICAL_ROUTE_CLEARANCE_UNVERIFIED","PASSENGER_OD_UNOBSERVED","STOP_SAFETY_UNVERIFIED"]
                outputs.append({"budget":result["budget"],"assumed_speed_kmh":scenario["assumed_speed_kmh"],
                    "scenario":arm,"selected_routes":selected,
                    "resident_coverage_proxy":result.get("covered_residents_estimate"),
                    "destinations":{k:v for k,v in ds.items() if k!="poi_indices"},
                    "transfer_links":xfers,"isolated_routes":sorted(isolated),
                    "peak_sensitivity":peak,"desktop_checks":desktop_checks,
                    "desktop_status":desktop_status,
                    "future_extension_candidates":[k for k in points if k not in active][:10],
                    "operational_gate":"REJECTED_PENDING_CRITICAL_EVIDENCE",
                    "gate_reasons":reasons})
    return {"status":"EXPLORATORY_MULTICRITERIA_SCREEN_NOT_APPROVED",
        "options_evaluated":len(outputs),"peak_slowdown_hypothesis":peak_slowdown,
        "straight_line_transfer_threshold_m":250,"poi_reach_radius_proxy_m":450,
        "proposals":outputs,"approved_operational_proposals":0,
        "limitations":["Only original population-coverage CP-SAT selections are evaluated, not optimized against POI/transfer objectives",
                       "POI counts measure mapped destinations, not actual patronage or opening hours",
                       "Straight-line transfers are not walk-network accessibility",
                       "Expected headway/2 wait assumes random arrivals, no coordination",
                       "Peak multiplier is hypothetical; no traffic observations",
                       "Expansion list is not a valid phasing or extension design"]}

def main():
    p=argparse.ArgumentParser()
    for arg in ("fleet","routes","pois","output"):p.add_argument("--"+arg,type=Path,required=True)
    args=p.parse_args()
    result=assess(json.loads(args.fleet.read_text()),json.loads(args.routes.read_text())["features"],
                  json.loads(args.pois.read_text())["features"])
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print(json.dumps({"proposals":result["options_evaluated"],"approved":0}))
if __name__=="__main__":main()
