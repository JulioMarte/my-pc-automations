"""Conservative, *non-certifying* Yutong physical screening on directed OSM.

Shapely rigid-body polygon union estimates a conceptual swept envelope.
It is NOT an Ackermann steering/swept-path simulation. Without measured road
curbs and permitted turn movements, all non-explicitly forbidden corridors
remain DUDOSO; none are VIABLE. No cost/fleet ranking can override this.
"""
import argparse,json,math
from pathlib import Path
from shapely.geometry import Polygon,mapping
from shapely.ops import unary_union

def local_xy(coords,origin):
    scale=111195.0;factor=math.cos(math.radians(origin[1]))
    return [((p[0]-origin[0])*scale*factor,(p[1]-origin[1])*scale) for p in coords]

def body_polygon(x,y,angle,length=12.17,width=2.55,wheelbase=6.0,front=2.74,rear=3.43):
    if abs((wheelbase+front+rear)-length)>.01:raise ValueError("Bus geometry inconsistent")
    # polygon body is centered at a theoretical front-axle-to-rear-axle midpoint.
    half_forward=wheelbase/2+front
    half_back=wheelbase/2+rear
    ca,sa=math.cos(angle),math.sin(angle)
    corners=[]
    for dx,dy in ((-half_back,-width/2),(half_forward,-width/2),
                  (half_forward,width/2),(-half_back,width/2)):
        corners.append((x+dx*ca-dy*sa,y+dx*sa+dy*ca))
    return Polygon(corners)

def envelope(coords,dimensions,sample_step_m=2):
    if len(coords)<2:return None
    p=local_xy(coords,coords[0]);shapes=[]
    for (x,y),(u,v) in zip(p,p[1:]):
        dx,dy=u-x,v-y;length=math.hypot(dx,dy)
        if length<1e-4:continue
        angle=math.atan2(dy,dx)
        for k in range(max(2,math.ceil(length/sample_step_m)+1)):
            t=k/max(1,math.ceil(length/sample_step_m))
            shapes.append(body_polygon(x+t*dx,y+t*dy,angle,**dimensions))
    if not shapes:return None
    return unary_union(shapes)

def assess(candidates,config):
    v=config["vehicle"]
    dimensions=dict(length=v["length_m"],width=v["width_m"],wheelbase=v["wheelbase_m"],
                    front=v["front_overhang_m"],rear=v["rear_overhang_m"])
    required=[float(x) for x in v["turning_circle_diameters_sensitivity_m"]]
    if sorted(required)!=[20.5,21.5]:raise ValueError("Unexpected Yutong turn sensitivity")
    results=[]
    for c in candidates["candidates"]:
        coords=c["geometry"]["coordinates"]
        e=envelope(coords,dimensions)
        if e is None:
            status="INVIABLE"
            reasons=["DEGENERATE_ROUTE_CENTERLINE"]
        else:
            status="DUDOSO"
            reasons=["UNKNOWN_CURB_TO_CURB_WIDTH","NO_INDEPENDENT_TURN_RESTRICTION_AUDIT",
                     "TERMINAL_TURNAROUND_UNVERIFIED","RIGID_ENVELOPE_NOT_STEERING_MODEL"]
        results.append({"candidate":c["id"],"status":status,
                        "vehicle":"Yutong ZK6126HG",
                        "turning_diameter_sensitivity_m":required,
                        "theoretical_rigid_body_envelope_area_m2":round(e.area,1) if e else None,
                        "envelope_is_clearance_certification":False,
                        "bus_viable_proven":False,
                        "blocking_evidence":reasons,
                        "source_geometry":"OSM directed graph centerline; no surveyed curbs"})
    return {"status":"ALL_NONDEGENERATE_ROUTES_DOUBTFUL_PENDING_PHYSICAL_EVIDENCE",
        "audited":len(results),"VIABLE":sum(x["status"]=="VIABLE" for x in results),
        "DUDOSO":sum(x["status"]=="DUDOSO" for x in results),
        "INVIABLE":sum(x["status"]=="INVIABLE" for x in results),
        "results":results,
        "physical_approval":False,
        "limitations":["Shapely rigid envelopes do NOT replicate steering kinematics or passenger-car stop behavior",
                       "No actual curb boundaries, heights, gradients, mirror clearance or junction turn restrictions",
                       "Both documented reference turning circles remain uncertain for selected bus variant",
                       "Curb clearance needs audited physical geometry before VIABLE"]}

def main():
    p=argparse.ArgumentParser()
    for name in ("candidates","config","output"):p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args()
    r=assess(json.loads(a.candidates.read_text()),json.loads(a.config.read_text()))
    a.output.write_text(json.dumps(r,ensure_ascii=False))
    print(json.dumps({"audited":r["audited"],"viable":r["VIABLE"],"doubtful":r["DUDOSO"],"inviable":r["INVIABLE"]}))
if __name__=="__main__":main()
