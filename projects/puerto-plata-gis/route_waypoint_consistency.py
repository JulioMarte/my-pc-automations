"""Check whether terminal-to-terminal Valhalla route actually serves candidate waypoints.

Distance to routed centerline is planar/local approximate and only diagnoses
routing consistency. This does NOT establish safe or accessible bus stops.
"""
import argparse,json,math
from pathlib import Path
M=111195.0

def distance_to_segments(point,coords):
    lat=math.radians(point[1])
    scale=M*math.cos(lat)
    def xy(p):return ((p[0]-point[0])*scale,(p[1]-point[1])*M)
    best=float("inf")
    for a,b in zip(coords,coords[1:]):
        ax,ay=xy(a);bx,by=xy(b)
        dx,dy=bx-ax,by-ay
        denom=dx*dx+dy*dy
        t=max(0,min(1,-(ax*dx+ay*dy)/denom)) if denom>0 else 0
        best=min(best,math.hypot(ax+t*dx,ay+t*dy))
    return best

def audit(routes,paths,threshold_m=80.0):
    if threshold_m<=0:raise ValueError("Invalid threshold")
    by_route={}
    for feat in paths.get("features",[]):
        p=feat.get("properties") or {}
        key=(p.get("candidate"),p.get("direction"))
        by_route[key]=feat.get("geometry",{}).get("coordinates",[])
    rows=[]
    for feature in routes.get("features",[]):
        props=feature.get("properties") or {}
        candidate=props.get("id")
        coords=feature.get("geometry",{}).get("coordinates",[])
        if feature.get("geometry",{}).get("type")!="MultiPoint" or not coords:continue
        direction_results={}
        for direction in ("outbound","inbound"):
            line=by_route.get((candidate,direction)) or []
            distances=[round(distance_to_segments(p,line),2) if len(line)>=2 else None for p in coords]
            misses=[{"index":i,"distance_m":d} for i,d in enumerate(distances) if d is None or d>threshold_m]
            direction_results[direction]={"routed_shape_exists":bool(line),"waypoint_count":len(coords),
                "missed_waypoints":misses,"max_waypoint_deviation_m":max((d for d in distances if d is not None),default=None),
                "all_waypoints_near_graph_route":len(misses)==0}
        rows.append({"candidate":candidate,"directions":direction_results,
                     "actual_stops_served_verified":False})
    problematic=[r["candidate"] for r in rows if any(not d["all_waypoints_near_graph_route"] for d in r["directions"].values())]
    return {"status":"ROUTE_WAYPOINT_CONSISTENCY_NOT_BUS_STOP_APPROVAL",
            "threshold_m":threshold_m,"routes_checked":len(rows),
            "routes_with_waypoint_deviation":problematic,
            "routes":rows,"bus_stop_accessibility_verified":False,
            "note":"MultiPoint may include stops assigned to a return direction; this audit conservatively tests both directions and flags review, not impossibility."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--candidates",type=Path,required=True)
    p.add_argument("--routes",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    result=audit(json.loads(a.candidates.read_text()),json.loads(a.routes.read_text()))
    a.output.write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print(json.dumps({"checked":result["routes_checked"],"with_waypoint_deviation":len(result["routes_with_waypoint_deviation"])}))
if __name__=="__main__":main()
