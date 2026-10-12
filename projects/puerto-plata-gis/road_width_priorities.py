"""Prioritize road inspection transects near the 10-bus candidate route stops.

These route GeoJSON geometries are MultiPoint, not verified road paths.
Near-stop sampling prioritizes field survey only; never approves corridor.
"""
import argparse, json, math
from pathlib import Path

TARGET=("C00-09","C00-10","C02-04")
M=111195.0

def prioritize(transects, candidates, threshold_m=120, limit=30000):
    if threshold_m<=0 or limit<1:raise ValueError("Invalid radius or limit")
    stops={}
    for f in candidates:
        rid=f.get("properties",{}).get("id")
        if rid not in TARGET or f.get("geometry",{}).get("type")!="MultiPoint":continue
        stops[rid]=[tuple(p[:2]) for p in f["geometry"]["coordinates"]]
    if set(TARGET)!=set(stops):
        raise ValueError("Missing candidate route stops: "+str(set(TARGET)-set(stops)))
    pts=[(rid,lon,lat) for rid,arr in stops.items() for lon,lat in arr]
    results=[]
    full_counts=dict.fromkeys(TARGET,0)
    for f in transects:
        c=f.get("geometry",{}).get("coordinates",[])
        if len(c)!=2:continue
        lon,lat=(c[0][0]+c[1][0])/2,(c[0][1]+c[1][1])/2
        cos=math.cos(math.radians(lat))
        matching=set()
        for rid,x,y in pts:
            dx=(x-lon)*M*cos
            dy=(y-lat)*M
            if dx*dx+dy*dy<=threshold_m*threshold_m:matching.add(rid)
        if not matching:continue
        for rid in matching:full_counts[rid]+=1
        if len(results)<limit:
            feature={"type":"Feature","geometry":f["geometry"],
                     "properties":dict(f.get("properties",{}))}
            feature["properties"].update({
                "priority_for":sorted(matching),
                "matching_type":"NEAR_PROVISIONAL_STOPS_ONLY",
                "road_width_m":None,"bus_approved":False})
            results.append(feature)
    return {"type":"FeatureCollection",
            "metadata":{"status":"PRIORITIZED_TRANSECTS_NOT_ROAD_WIDTHS",
                        "target_routes":list(TARGET),"stop_buffer_m":threshold_m,
                        "total_by_route_before_export_limit":full_counts,
                        "export_limit":limit,"exported":len(results),
                        "truncated":sum(full_counts.values())>0 and len(results)>=limit},
            "features":results}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--transects",type=Path,required=True)
    p.add_argument("--routes",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--radius",type=float,default=120)
    a=p.parse_args()
    x=prioritize(json.loads(a.transects.read_text())["features"],
                 json.loads(a.routes.read_text())["features"],a.radius)
    a.output.write_text(json.dumps(x,ensure_ascii=False))
    print(json.dumps(x["metadata"]))
if __name__=="__main__": main()
