"""Vehicle swept-envelope sensitivity is screening ONLY without observed curbs.

Polygon footprints use Shapely on a local tangent metric projection.
At each centreline vertex the bus longitudinal axis follows the road;
this is NOT a steering/kinematic swept-path solution and NO pedestrian
or curb obstacles are currently available. Never mark VIABLE from this.
"""
import json,math,argparse
from pathlib import Path
from shapely.geometry import Polygon
from shapely.ops import unary_union

def point_xy(coord,origin):
    lat0=math.radians(origin[1])
    return ((coord[0]-origin[0])*111195*math.cos(lat0),
            (coord[1]-origin[1])*111195)

def vehicle_polygon(point,heading,vehicle):
    length=vehicle["length_m"];width=vehicle["width_m"]
    wheelbase=vehicle["axle_spacing_m"];front=vehicle["front_overhang_m"];rear=vehicle["rear_overhang_m"]
    if abs((wheelbase+front+rear)-length)>.01:raise ValueError("Vehicle dimensions do not add up")
    # Position point is the rear-axle reference; rear overhang negative.
    corners=[(-rear,-width/2),(-rear,width/2),(wheelbase+front,width/2),(wheelbase+front,-width/2)]
    c,s=math.cos(heading),math.sin(heading)
    return Polygon([(point[0]+u*c-v*s,point[1]+u*s+v*c) for u,v in corners])

def inspect(feature,config):
    coords=feature["geometry"]["coordinates"]
    vehicle=config["vehicle"]
    if len(coords)<3:return {"status":"DUDOSO","blockers":["INSUFFICIENT_CENTERLINE_POINTS"]}
    base=coords[0]
    xy=[point_xy(p,base) for p in coords]
    polygons=[]
    angles=[]
    for i,p in enumerate(xy):
        before=xy[max(i-1,0)];after=xy[min(i+1,len(xy)-1)]
        heading=math.atan2(after[1]-before[1],after[0]-before[0])
        polygons.append(vehicle_polygon(p,heading,vehicle))
        if 0<i<len(xy)-1:
            a=math.atan2(p[1]-before[1],p[0]-before[0])
            b=math.atan2(after[1]-p[1],after[0]-p[0])
            angles.append(abs(math.degrees(math.atan2(math.sin(b-a),math.cos(b-a)))))
    radii=[]
    for a,b,c in zip(xy,xy[1:],xy[2:]):
        la=math.dist(a,b);lb=math.dist(b,c);lc=math.dist(a,c)
        twice_area=abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
        if twice_area>1e-5 and min(la,lb,lc)>1:
            radii.append((la*lb*lc)/(2*twice_area))
    min_radius=min(radii) if radii else None
    turning_sensitivity=[{"reference_diameter_m":d,
       "minimum_centerline_radius_proxy_m":round(min_radius,2) if min_radius is not None else None,
       "tight_curve_warning_only":min_radius is not None and min_radius<d/2,
       "approval":"DUDOSO_NO_CURB_OBSTACLE_GEOMETRY"} for d in vehicle["turning_diameter_scenarios_m"]]
    geom=unary_union(polygons)
    # Local polygon snapshots, not continuous kinematic trajectory.
    return {"status":"DUDOSO","max_centerline_deflection_deg":round(max(angles or [0]),2),
        "pose_footprint_union_area_m2":round(geom.area,2),
        "turning_diameter_reference_m":vehicle["turning_diameter_scenarios_m"],
        "turning_sensitivity":turning_sensitivity,
        "blockers":["NO_CURB_POLYGONS","NO_OBSTACLE_GEOMETRY","STEERING_PATH_NOT_VALIDATED",
                    "NO_VERIFIED_TERMINAL_TURN","GRADE_AND_OVERHEAD_CLEARANCE_NOT_VERIFIED"],
        "provenance":{"vehicle":"Yutong ZK6126HG config geometry",
                      "street_geometry":"OSM centreline; not curb positions",
                      "turning_diameters":"reference variants 20.5m and 21.5m, not measured envelope"},
        "physically_approved":False}

def audit(collection,config):
    rows=[]
    for f in collection["features"]:
        result=inspect(f,config)
        rows.append({"candidate_id":f["properties"]["candidate_id"],**result})
    return {"status":"ALL_UNMEASURED_TURNS_BLOCKED_FOR_APPROVAL",
       "vehicle":config["vehicle"]["model"],"results":rows,
       "viable_confirmed":0,"doubtful":sum(x["status"]=="DUDOSO" for x in rows),
       "unfeasible_confirmed":0,
       "note":"Shapely envelopes have no measured curbs or continuous steering trajectory; DUDOSO is not a pass."}

def main():
    p=argparse.ArgumentParser()
    for n in ("candidates","config","output"):p.add_argument("--"+n,type=Path,required=True)
    a=p.parse_args()
    x=audit(json.loads(a.candidates.read_text()),json.loads(a.config.read_text()))
    a.output.write_text(json.dumps(x))
    print(json.dumps({"candidates":len(x["results"]),"doubtful":x["doubtful"],"viable_confirmed":0}))
if __name__=="__main__":main()
