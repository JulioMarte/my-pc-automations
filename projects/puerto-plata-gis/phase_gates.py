"""Acceptance gates. A green workflow is NOT a completed planning phase.

Inputs are produced artifacts and a declared vehicle datasheet. Missing evidence
blocks acceptance. The gate report can be audited independently.
"""
from __future__ import annotations
import argparse,json,math
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def present(p):return p is not None and Path(p).is_file() and Path(p).stat().st_size>0
def check(config,root=ROOT,evidence=None):\n evidence=evidence or {}
 vehicle=config["vehicle"];data=config["data"]
 resolve=lambda k:root/data[k] if data.get(k) else None
 physical=all(isinstance(vehicle.get(k),(float,int)) and vehicle[k]>0 for k in
              ("length_m","width_m","minimum_turning_radius_m","maximum_grade_percent"))
 tests={}
 tests["vehicle_specification"]=bool(physical and vehicle.get("datasheet_verified"))
 tests["crs_configured"]=config.get("study_crs")=="EPSG:32619"
 tests["gis_raw_inputs"]=all(present(resolve(x)) for x in ("population","destinations","drive_graph","walk_graph"))
 tests["dem_available"]=present(resolve("dem"))
 tests["valhalla_tiles"]=present(resolve("valhalla_tile_extract"))
 tests["observed_counts"]=present(resolve("observed_counts_csv"))
 tests["osm_pbf"]=present(resolve("osm_pbf"))
 tests["gtfs"]=present(resolve("gtfs"))
 def gate(name,requirements,note):
  unmet=[r for r in requirements if not tests[r]]
  return {"phase":name,"status":"APROBADO" if not unmet else "BLOQUEADO",
          "missing_requirements":unmet,"note":note}
 phases=[
  gate(0,["gis_raw_inputs","crs_configured","dem_available","valhalla_tiles"],"Requires geometry/CRS validator separately before sign-off; presence is insufficient."),
  gate(1,["vehicle_specification","valhalla_tiles","dem_available"],"Must inspect all bus transitions and terrain slope per edge; presence alone is insufficient."),
  gate(2,["vehicle_specification","observed_counts"],"L1 2-way driveability, measured cycle and stop safety remain unverified."),
  gate(3,["gis_raw_inputs"],"H3 zones, hubs and employment validation remain unverified."),
  gate(4,["observed_counts"],"Synthetic OD scores cannot be treated as measured travel demand."),
  gate(5,["vehicle_specification","valhalla_tiles"],"Requires >=50 valid bus candidates and swept-path approval."),
  gate(6,["observed_counts","vehicle_specification"],"Requires demand/capacity-validated ranking."),
  gate(7,["vehicle_specification","observed_counts"],"Requires budget-optimal network with and without L1 and actual cycle times."),
  gate(8,["osm_pbf","gtfs"],"Requires observed/modeled multimodal travel-time evaluation."),
  gate(9,["observed_counts","vehicle_specification","osm_pbf","gtfs"],"Requires accepted final map and sensitivity report.")]
 # No phase is auto-approved based on file presence: manual acceptance evidence
 for item in phases:
  item["preconditions_met"]=item["status"]=="APROBADO"
  item["status"]="BLOQUEADO"
  item["acceptance"]="manual engineering evidence not supplied"
 return {"policy":"conservative: no phase approved without field/algorithm acceptance evidence",
 "requirements":tests,"phase_gates":phases}
def main():
 p=argparse.ArgumentParser();p.add_argument("--root",type=Path,default=ROOT)
 p.add_argument("--config",type=Path,default=ROOT/"study_config.json")
 p.add_argument("--output",type=Path,default=ROOT/"phase_gates.json")\n p.add_argument("--evidence",type=Path,help="Manual signoff JSON per phase with reviewed, reviewer, artifact_sha256 and acceptance_tests_passed")
 a=p.parse_args();d=json.loads(a.config.read_text());r=check(d,a.root,json.loads(a.evidence.read_text()) if a.evidence else None)
 a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2))
 print("Phase gates",[(x["phase"],x["status"]) for x in r["phase_gates"]])
if __name__=="__main__":main()
