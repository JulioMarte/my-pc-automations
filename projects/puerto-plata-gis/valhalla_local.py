"""Local Valhalla Python binding audit. No server, no HTTP, no guessed success.

Requires: pip install pyvalhalla
Requires pre-built local Valhalla tiles (graph produced from OSM PBF).
This is a routing-engine check, NOT bus swept-path or field validation.
"""
from __future__ import annotations
import argparse,json,csv
from pathlib import Path
from valhalla_audit import pairs
from valhalla_route_shape import extract_shape

ROOT=Path(__file__).resolve().parent
def audit(features, actor, limit=6):
 output={"backend":"pyvalhalla Actor (in process)","status":"local_route_checks_completed",
 "limitations":["Bus costing relies on OSM restrictions; no validated turning radius or physical median opening",
 "A-to-B and B-to-A are individually routed; terminal turn continuity is NOT checked",
 "Candidate MultiPoint endpoints may not correspond to operational terminals"],
 "routes":[]}
 for item in pairs(features)[:limit]:
  row={"id":item["id"],"outbound":None,"inbound":None,
       "routed_both_directions":False,"bus_geometry_validated":False}
  for direction,a,b in (("outbound",item["a"],item["b"]),("inbound",item["b"],item["a"])):
   request={"locations":[{"lat":a[1],"lon":a[0]},{"lat":b[1],"lon":b[0]}],"costing":"bus","directions_options":{"units":"kilometers"}}
   try:
    result=actor.route(request)
    if isinstance(result,str):result=json.loads(result)
    summary=result["trip"]["summary"]
    if not isinstance(summary.get("length"),(int,float)) or summary["length"]<=0.1 or not isinstance(summary.get("time"),(int,float)) or summary["time"]<=0:
     raise ValueError("Degenerate zero/short route; terminal data or network snapping invalid")
    row[direction]={"status":"routed","distance_km":summary.get("length"),"time_seconds":summary.get("time"),"road_shape":extract_shape(result)}
   except Exception as exc:
    row[direction]={"status":"error","message":str(exc)[:250]}
  row["routed_both_directions"]=all(row[d]["status"]=="routed" for d in ("outbound","inbound"))
  row["turn_audit"]=[{"candidate":item["id"],"point":{"lon":pt[0],"lat":pt[1]},"vehicle":"Yutong ZK6126HG (reference; no swept path approval)","reason":("Both directional routes found, but terminal swept-path and median crossings unverified" if row["routed_both_directions"] else "At least one direction cannot be routed by Valhalla on current OSM tiles"),"status":"REVIEW_REQUIRED" if row["routed_both_directions"] else "BLOCKED"} for pt in (item["a"],item["b"])]
  output["routes"].append(row)
 return output
def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--input",default=str(ROOT/"discovered_routes.geojson"))
 ap.add_argument("--output",default=str(ROOT/"valhalla_local_audit.json"))
 ap.add_argument("--tiles",required=True,help="Existing local Valhalla tile archive (tar)")
 ap.add_argument("--limit",type=int,default=6)
 args=ap.parse_args()
 tile_path=Path(args.tiles).resolve()
 if not tile_path.is_file():raise FileNotFoundError(f"Tiles do not exist: {tile_path}")
 try:from valhalla import Actor,get_config
 except ImportError as e:raise RuntimeError("Install pyvalhalla: pip install pyvalhalla") from e
 actor=Actor(get_config(tile_dir=str(tile_path.parent/"tiles"), tile_extract=str(tile_path)))
 features=json.loads(Path(args.input).read_text())["features"]
 report=audit(features,actor,args.limit)
 from valhalla_waypoint_route import route_waypoints,to_geojson
 waypoint_report=route_waypoints(features,actor)
 (ROOT/"valhalla_waypoint_constrained.json").write_text(json.dumps(waypoint_report,indent=2,ensure_ascii=False))
 (ROOT/"valhalla_waypoint_constrained.geojson").write_text(json.dumps(to_geojson(waypoint_report),ensure_ascii=False,separators=(",",":")))
 print("Waypoint-constrained routes:",waypoint_report["complete_routes"],"/",len(waypoint_report["routes"]))

 report["tile_extract"]=str(tile_path)
 Path(args.output).write_text(json.dumps(report,indent=2,ensure_ascii=False))
 csv_path=Path(args.output).with_name("valhalla_turn_audit.csv")
 with csv_path.open("w",newline="",encoding="utf-8") as f:
  writer=csv.DictWriter(f,fieldnames=["candidate","latitude","longitude","vehicle","status","reason"])
  writer.writeheader()
  for route in report["routes"]:
   for item in route["turn_audit"]:
    writer.writerow({"candidate":item["candidate"],"latitude":item["point"]["lat"],"longitude":item["point"]["lon"],"vehicle":item["vehicle"],"status":item["status"],"reason":item["reason"]})
 print(f"Audited {len(report['routes'])} routes using local Valhalla Python bindings")
if __name__=="__main__":main()
