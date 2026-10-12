"""Make exact coverage-by-cell inputs for OR-Tools; require sourced cycle CSV.

Cycles CSV columns: route_id,cycle_minutes,cycle_source,operational_geometry_approved
cycle_source: measured|calibrated_simulation|uncalibrated_simulation
Missing cycles are not filled from generic speeds; FAIL CLOSED.
"""
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
import osmnx as ox
from network_access import Network
from discover_transit_network import preproject,reached

ROOT=Path(__file__).resolve().parent
def load_cycles(path):
 cycles={}
 with path.open(newline="",encoding="utf-8") as f:
  for line in csv.DictReader(f):
   key=line.get("route_id","").strip()
   if not key or key in cycles:raise ValueError("Missing or duplicated route ID")
   try:value=float(line["cycle_minutes"])
   except (KeyError,ValueError,TypeError):raise ValueError(f"Missing measured/simulated cycle for {key}")
   if value<=0:raise ValueError("Nonpositive cycle")
   source=line.get("cycle_source","").strip()
   if source not in {"measured","calibrated_simulation","uncalibrated_simulation"}:raise ValueError("Missing cycle provenance")
   valid=line.get("operational_geometry_approved","").strip().lower()
   if valid not in {"true","false"}:raise ValueError("Geometry approval must be explicitly true or false")
   cycles[key]={"cycle_minutes":value,"cycle_source":source,"operational_geometry_approved":valid=="true"}
 return cycles

def build(g,pop,features,cycles,max_snap=60,radius=500):
 network=Network(g)
 west,south,east,north=-70.752,19.740,-70.620,19.836
 in_bounds=[(lat,lon,val) for lat,lon,val in pop if west<=lon<=east and south<=lat<=north and val>0]
 projected,_=preproject(network,in_bounds,[],max_snap)
 output={"cells":{str(i):float(p[2]) for i,p in enumerate(in_bounds)},"routes":[]}
 for f in features:
  name=f.get("properties",{}).get("id")
  if not name:raise ValueError("Route without id")
  if name not in cycles:raise ValueError(f"No cycle evidence for {name}")
  pts=f.get("geometry",{}).get("coordinates",[])
  if f.get("geometry",{}).get("type")!="MultiPoint" or not pts:raise ValueError(f"Route {name} has no proposed stop points")
  stops=[[p[1],p[0]] for p in pts]
  indices=reached(network,stops,projected,radius=radius,max_snap=max_snap)
  output["routes"].append({"id":name,"covered_cells":[str(i) for i in sorted(indices)],**cycles[name]})
 return output

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--root",type=Path,default=ROOT)
 ap.add_argument("--cycles-csv",type=Path,required=True)
 ap.add_argument("--output",type=Path,default=ROOT/"optimization_input.json")
 args=ap.parse_args();root=args.root
 cycles=load_cycles(args.cycles_csv)
 features=json.loads((root/"discovered_routes.geojson").read_text())["features"]
 pop=json.loads((root/"population.json").read_text())["cells"]
 g=ox.load_graphml(root/"walk.graphml")
 report=build(g,pop,features,cycles)
 args.output.write_text(json.dumps(report))
 print("Routes",len(report["routes"]),"cells",len(report["cells"]))
if __name__=="__main__":main()
