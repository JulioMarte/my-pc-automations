"""Run the real in-process Valhalla engine on a reproducible Geofabrik PBF.

Regardless of success, write a machine-readable evidence report. An unsuccessful
tile build or route query is BLOCKED_WITH_EVIDENCE, never a synthetic pass.
"""
from __future__ import annotations
import argparse,datetime,json,subprocess,time,traceback,hashlib
from pathlib import Path

SOURCE="https://download.geofabrik.de/central-america/haiti-and-domrep-latest.osm.pbf"
def command(args,timeout):
 start=time.monotonic()
 try:
  r=subprocess.run(args,text=True,capture_output=True,timeout=timeout,check=False)
  return {"cmd":args,"exit":r.returncode,"elapsed_s":round(time.monotonic()-start,1),
   "stdout_tail":r.stdout[-1500:],"stderr_tail":r.stderr[-2000:]}
 except Exception as e:
  return {"cmd":args,"exit":-1,"elapsed_s":round(time.monotonic()-start,1),"error":str(e)[:500]}
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--pbf",type=Path,required=True)
 p.add_argument("--routes",type=Path,required=True)
 p.add_argument("--output-dir",type=Path,required=True)
 p.add_argument("--limit",type=int,default=18)
 a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
 record={"source_url":SOURCE,"timestamp_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
 "status":"BLOCKED_WITH_EVIDENCE","pbf_exists":a.pbf.is_file(),"steps":[],"routing":None,
 "limitations":["No legal certification of turns, no swept-path assessment","Stops are provisional; endpoints are not certified terminals"]}
 try:
  if not a.pbf.is_file() or a.pbf.stat().st_size<500000:raise RuntimeError("Missing or unreasonably small OSM PBF")
  record["pbf_bytes"]=a.pbf.stat().st_size
  record["pbf_sha256"]=hashlib.sha256(a.pbf.read_bytes()).hexdigest()
  from valhalla import get_config,Actor
  graph=a.output_dir/"tiles";graph.mkdir(exist_ok=True)
  extract=a.output_dir/"valhalla_tiles.tar"
  cfg=get_config(tile_dir=str(graph.resolve()),tile_extract=str(extract.resolve()))
  config=a.output_dir/"valhalla.json";config.write_text(json.dumps(cfg))
  commands=[["python","-m","valhalla","valhalla_build_tiles","-c",str(config.resolve()),str(a.pbf.resolve())],
   ["python","-m","valhalla","valhalla_build_extract","-c",str(config.resolve())]]
  for c in commands:
   result=command(c,600);record["steps"].append(result)
   if result["exit"]!=0:raise RuntimeError("Tile build step failed: "+c[3])
  if not extract.is_file() or extract.stat().st_size<10000:raise RuntimeError("No usable local tile extract")
  actor=Actor(cfg)
  from valhalla_local import audit
  features=json.loads(a.routes.read_text())["features"]
  report=audit(features,actor,limit=a.limit)
  record["routing"]=report
  record["tile_extract_bytes"]=extract.stat().st_size
  record["routed_both_directions"]=sum(x["routed_both_directions"] for x in report["routes"])
  record["route_failures"]=[x["id"] for x in report["routes"] if not x["routed_both_directions"]]
  record["status"]="EXECUTED_ROUTES_REQUIRE_TURN_REVIEW"
 except Exception as exc:
  record["failure"]=str(exc)[:800]
  record["traceback_tail"]=traceback.format_exc()[-1200:]
 finally:
  (a.output_dir/"valhalla_execution_evidence.json").write_text(json.dumps(record,indent=2,ensure_ascii=False))
  if record["routing"]:
   with (a.output_dir/"turn_audit.csv").open("w",encoding="utf-8") as file:
    file.write("candidate,lat,lon,vehicle,status,reason\n")
    import csv
    w=csv.writer(file)
    for r in record["routing"]["routes"]:
     for t in r["turn_audit"]:
      w.writerow([r["id"],t["point"]["lat"],t["point"]["lon"],t["vehicle"],t["status"],t["reason"]])
  print(json.dumps({"status":record["status"],"routed_both_directions":record.get("routed_both_directions"),
                    "failure":record.get("failure")},ensure_ascii=False))
if __name__=="__main__":main()
