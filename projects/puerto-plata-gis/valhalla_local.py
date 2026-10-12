"""Local Valhalla Python binding audit. No server, no HTTP, no guessed success.

Requires: pip install pyvalhalla
Requires pre-built local Valhalla tiles (graph produced from OSM PBF).
This is a routing-engine check, NOT bus swept-path or field validation.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from valhalla_audit import pairs

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
    row[direction]={"status":"routed","distance_km":summary.get("length"),"time_seconds":summary.get("time")}
   except Exception as exc:
    row[direction]={"status":"error","message":str(exc)[:250]}
  row["routed_both_directions"]=all(row[d]["status"]=="routed" for d in ("outbound","inbound"))
  row["turn_audit"]=[{"candidate":item["id"],"point":{"lon":pt[0],"lat":pt[1]},"vehicle":"Mercedes-Benz Citaro K (reference)","reason":("Both directional routes found, but terminal swept-path and median crossings unverified" if row["routed_both_directions"] else "At least one direction cannot be routed by Valhalla on current OSM tiles"),"status":"REVIEW_REQUIRED" if row["routed_both_directions"] else "BLOCKED"} for pt in (item["a"],item["b"])]
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
 report["tile_extract"]=str(tile_path)
 Path(args.output).write_text(json.dumps(report,indent=2,ensure_ascii=False))
 print(f"Audited {len(report['routes'])} routes using local Valhalla Python bindings")
if __name__=="__main__":main()
