"""Exploratory, deliberately uncalibrated 10/20/30-bus coverage curve.

Uses actual GIS population cells and provisional route-stop coverage from the
previous jobs. Only the vehicle cycles are illustrative assumptions, not
measurements. This result must NEVER be presented as a fleet recommendation.
"""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
import osmnx as ox
from prepare_optimization_input import build
from optimize_headways import optimize

ROOT=Path(__file__).resolve().parent

def l1_outbound_length_km(fc):
 lines=[f["geometry"]["coordinates"] for f in fc["features"] if f.get("geometry",{}).get("type") in ("LineString",)]
 if not lines:raise ValueError("L1 outbound polyline absent: cannot calculate illustrative cycle")
 from pyproj import Transformer
 t=Transformer.from_crs("EPSG:4326","EPSG:32619",always_xy=True)
 coords=lines[0]
 metres=sum(math.hypot(t.transform(*b)[0]-t.transform(*a)[0],t.transform(*b)[1]-t.transform(*a)[1]) for a,b in zip(coords,coords[1:]))
 if metres<=0:raise ValueError("L1 length invalid")
 return metres/1000

def cycles_for_scenario(features,competition,l1_fc,speed_kmh=18,layover_minutes=12):
 lengths={r["id"]:r["round_trip_km"] for r in competition["competitors"] if r.get("round_trip_km")}
 lengths["L1"]=round(2*l1_outbound_length_km(l1_fc),3)
 if not 0<speed_kmh<=50 or layover_minutes<0:raise ValueError("Nonphysical scenario speed")
 data={}
 for f in features:
  id=f["properties"]["id"]
  length=lengths.get(id)
  if length is None or length<=0:raise ValueError(f"Missing route-distance evidence: {id}")
  data[id]={"cycle_minutes":round(60*length/speed_kmh+layover_minutes,2),
   "cycle_source":"uncalibrated_simulation","operational_geometry_approved":False}
 return data,lengths

def compute(root,speeds=(12,18,24),budgets=(10,20,30)):
 features=json.loads((root/"discovered_routes.geojson").read_text())["features"]
 competition=json.loads((root/"route_competition.json").read_text())
 l1=json.loads((root/"initial_route.geojson").read_text())
 pop=json.loads((root/"population.json").read_text())["cells"]
 graph=ox.load_graphml(root/"walk.graphml")
 cfg=json.loads((root/"study_config.json").read_text())
 scenarios=[]
 for speed in speeds:
  cycles,lengths=cycles_for_scenario(features,competition,l1,speed)
  data=build(graph,pop,features,cycles)
  kwargs={"routes":data["routes"],"cells":data["cells"],"budgets":budgets,
   "headways":cfg["transit"]["allowed_headways_minutes"],
   "reserve":cfg["transit"]["reserve_ratio"],"allow_unvalidated":True}
  scenarios.append({"assumed_speed_kmh":speed,"assumed_layover_minutes":12,
   "approx_round_trip_km":lengths,
   "with_l1":optimize(**kwargs,l1_required=True),
   "without_l1_constraint":optimize(**kwargs,l1_required=False)})
 return {"status":"EXPLORATORY_NOT_OPERATIONALLY_VALIDATED",
  "provenance":{"population":"WorldPop estimated raster cells","routing":"OSMnx directed candidate stops",
   "cycles":"distance/speed+layover hypotheticals; L1 length doubled outbound, NOT observed bus cycle",
   "assumed_speeds_kmh":list(speeds),"reserve_ratio":cfg["transit"]["reserve_ratio"],
   "vehicle":cfg["vehicle"]["name"],"vehicle_length_m":cfg["vehicle"]["length_m"],
   "turn_circle_reference_m":cfg["vehicle"].get("turning_circle_diameter_m"),
   "turn_circle_is_variant_reference_only":True,
   "vehicle_specific_swept_path_evaluated":False,
   "included_vehicle_turn_validation":False,"counts_observed":False,
   "objective":"maximum distinct population near proposed stops; ignores destination trips, transfer cost"},
  "scenarios":scenarios}

def main():
 p=argparse.ArgumentParser();p.add_argument("--root",type=Path,default=ROOT)
 p.add_argument("--output",type=Path,default=ROOT/"fleet_10_20_30_exploratory.json")
 a=p.parse_args();report=compute(a.root)
 a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 for s in report["scenarios"]:
  print("Assumed speed",s["assumed_speed_kmh"],"km/h")
  for label in ("with_l1","without_l1_constraint"):
   print(label,[(x["budget"],x["status"],x.get("covered_residents_estimate"),x.get("buses")) for x in s[label]])
if __name__=="__main__":main()
