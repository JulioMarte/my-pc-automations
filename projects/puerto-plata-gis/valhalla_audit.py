"""Build an honest Valhalla bus routing audit against proposed candidate terminal pairs.

Uses Valhalla API only when VALHALLA_URL is explicitly configured. By default,
exports pending audit requests and does not claim validated maneuvers.
Candidate geometries are stop MultiPoints, NOT road polylines.
"""
import os,json,argparse,urllib.request,urllib.parse
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def pairs(features):
 out=[]
 for f in features:
  props=f.get("properties",{})
  a,b=props.get("terminal_start"),props.get("terminal_end")
  if a is None or b is None:raise ValueError(f"Terminals not recorded for {props.get('id')}; cannot infer from round-trip MultiPoint")
  if len(a)!=2 or len(b)!=2 or abs(a[0]-b[0])+abs(a[1]-b[1])<0.0001:
   raise ValueError(f"Coincident or invalid terminals for {props.get('id')}")
  out.append({"id":props.get("id"),"a":a,"b":b,
   "source":"OSMnx route terminal anchors explicitly saved; physical turnaround not verified"})
 return out
def query(base,start,end):
 url=base.rstrip("/")+"/route"
 request={"locations":[{"lat":start[1],"lon":start[0]},{"lat":end[1],"lon":end[0]}],
          "costing":"bus","directions_options":{"units":"kilometers"}}
 body=json.dumps(request).encode()
 req=urllib.request.Request(url,data=body,headers={"Content-Type":"application/json","User-Agent":"PuertoPlataGIS/0.3"},method="POST")
 with urllib.request.urlopen(req,timeout=50) as response:return json.load(response)
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--input",default=str(ROOT/"discovered_routes.geojson"))
 ap.add_argument("--output",default=str(ROOT/"valhalla_audit.json"))
 ap.add_argument("--url",default=os.environ.get("VALHALLA_URL",""))
 ap.add_argument("--limit",type=int,default=6)
 args=ap.parse_args()
 items=pairs(json.loads(Path(args.input).read_text())["features"])[:args.limit]
 output={"backend":"Valhalla","backend_configured":bool(args.url),"status":"pending",
 "interpretation":"Bus costing obeys mapped access and turn restrictions; never proves physical turning radius, median openings or safe stops",
 "routes":[]}
 for item in items:
  row={"id":item["id"],"endpoints":item,"outbound":None,"inbound":None,
       "road_graph_bus_candidate":False,"turning_radius_validated":False,"terminal_turn_validated":False}
  if args.url:
   for direction,a,b in (("outbound",item["a"],item["b"]),("inbound",item["b"],item["a"])):
    try:
     r=query(args.url,a,b)
     leg=r["trip"]["legs"][0];summary=r["trip"]["summary"]
     row[direction]={"distance_km":summary.get("length"),"time_seconds":summary.get("time"),
       "maneuvers":len(leg.get("maneuvers",[])),"status":"routed"}
    except Exception as e:row[direction]={"status":"error","message":str(e)[:220]}
   row["road_graph_bus_candidate"]=all(row[x] and row[x].get("status")=="routed" for x in ("outbound","inbound"))
  output["routes"].append(row)
 output["status"]="routing_requests_completed" if args.url else "unconfigured_no_routing_claim"
 Path(args.output).write_text(json.dumps(output,indent=2,ensure_ascii=False))
 print(f"Valhalla configured={bool(args.url)}; {len(items)} candidates; status={output['status']}")
if __name__=="__main__":main()
