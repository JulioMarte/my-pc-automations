"""Compare network-level service scenarios without pretending to validate bus maneuvers.

Inputs: scenario JSON containing candidate STOP points, actual WorldPop/Overture
and walking OSMnx graph. Marginal access is computed on the union of routes
to avoid double-counting. Vehicle-leg feasibility is a separate gate.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
import osmnx as ox
from network_access import coverage

ROOT=Path(__file__).resolve().parent

def read_stops(path):
 data=json.loads(Path(path).read_text())
 if data.get("type")!="FeatureCollection":raise ValueError("Expected GeoJSON FeatureCollection")
 return [[f["geometry"]["coordinates"][1],f["geometry"]["coordinates"][0]]
  for f in data["features"] if f.get("geometry",{}).get("type")=="Point" and
  (f.get("properties",{}).get("kind") in ("stop",None))]

def compute(g,population,destinations,scenarios,radius=500):
 if not scenarios:raise ValueError("No scenarios")
 outputs=[];baseline=None
 poi_cells=[[f["geometry"]["coordinates"][1],f["geometry"]["coordinates"][0],1]
     for f in destinations if f.get("geometry",{}).get("type")=="Point"]
 for scenario in scenarios:
  stops=[]
  for r in scenario["routes"]:
   stops.extend(r["stops"])
  if not stops:raise ValueError("Scenario without stops")
  people=coverage(g,stops,population,radius=radius)
  pois=coverage(g,stops,poi_cells,radius=radius)
  row={"name":scenario["name"],"route_count":len(scenario["routes"]),
   "stop_count":len(stops),"walk_access_residents":people["residents"],
   "walk_access_pois":pois["residents"],
   "bus_geometry_validated":all(r.get("bus_geometry_validated") is True for r in scenario["routes"]),
   "limitations":"union walking access only; no OD, journey times, transfers, fare or road maneuver approval"}
  if baseline is None:baseline=(row["walk_access_residents"],row["walk_access_pois"])
  row["additional_residents_vs_baseline"]=row["walk_access_residents"]-baseline[0]
  row["additional_pois_vs_baseline"]=row["walk_access_pois"]-baseline[1]
  outputs.append(row)
 return {"metadata":{"radius_m":radius,"comparison":"union of stops per scenario",
   "population":"WorldPop estimates; not observed passengers",
   "destinations":"Overture places records; not independently verified or deduplicated",
   "note":"Do not rank as feasible unless bus_geometry_validated is true; even true requires independent operational review"},
   "scenarios":outputs}

def main():
 p=argparse.ArgumentParser()
 p.add_argument("--graph",default=str(ROOT/"walk.graphml"))
 p.add_argument("--population",default=str(ROOT/"population.json"))
 p.add_argument("--destinations",default=str(ROOT/"destinations.geojson"))
 p.add_argument("--baseline",default=str(ROOT/"initial_route.geojson"))
 p.add_argument("--scenario-config")
 p.add_argument("--output",default=str(ROOT/"network_scenario_comparison.json"))
 a=p.parse_args()
 g=ox.load_graphml(a.graph)
 pop=json.loads(Path(a.population).read_text())["cells"]
 places=json.loads(Path(a.destinations).read_text())["features"]
 if a.scenario_config:
  scenarios=json.loads(Path(a.scenario_config).read_text())["scenarios"]
 else:
  scenarios=[{"name":"L1 existing preliminary","routes":[{"id":"L1",
      "stops":read_stops(a.baseline),"bus_geometry_validated":False}]}]
 report=compute(g,pop,places,scenarios)
 Path(a.output).write_text(json.dumps(report,indent=2))
 print(json.dumps(report,indent=2))
if __name__=="__main__":main()
