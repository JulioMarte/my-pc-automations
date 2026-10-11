"""Discover and compare candidate bus corridors and complementary networks.

Exploratory graph search, not an approved bus routing or an observed OD forecast.
Uses WorldPop, Overture and directed OSM road/walk graphs. All routes unvalidated.
"""
from __future__ import annotations
import argparse,json,math,itertools,heapq
from collections import defaultdict
from pathlib import Path
import networkx as nx
import osmnx as ox
from scipy.spatial import cKDTree
from network_access import Network,xy

ROOT=Path(__file__).resolve().parent
BBOX=(-70.752,19.740,-70.620,19.836)
def nearest_drive(g,coords):
 nodes=list(g.nodes)
 lat0=19.79
 tree=cKDTree([xy(g.nodes[n]["y"],g.nodes[n]["x"],lat0) for n in nodes])
 return [nodes[int(i)] for i in tree.query([xy(a,b,lat0) for a,b in coords])[1]]
def sample_path(g,path,spacing=450):
 if not path:return []
 result=[path[0]];length=0.
 for u,v in zip(path,path[1:]):
  edges=g.get_edge_data(u,v)
  length+=min(float(d.get("length",0)) for d in edges.values())
  if length>=spacing:
   result.append(v);length=0.
 if path[-1]!=result[-1]:result.append(path[-1])
 return [[g.nodes[n]["y"],g.nodes[n]["x"]] for n in result]
def route(g,a,b):
 forward=nx.shortest_path(g,a,b,weight="length")
 reverse=nx.shortest_path(g,b,a,weight="length")
 def metres(path):
  return sum(min(float(d.get("length",0)) for d in g.get_edge_data(u,v).values()) for u,v in zip(path,path[1:]))
 km=(metres(forward)+metres(reverse))/1000
 # Two graph-connected paths can still demand illegal turn transitions at terminals.
 return {"stops":sample_path(g,forward)+sample_path(g,reverse),
  "forward_km":round(metres(forward)/1000,2),"reverse_km":round(metres(reverse)/1000,2),
  "round_trip_km":round(km,2),"forward_nodes":forward,"reverse_nodes":reverse,
  "turns_verified":False}
def anchor_points(g,pop,poi):
 # Weighted high-population 0.012-degree grid, not assumed place-name coordinates.
 grid=defaultdict(float); points=defaultdict(lambda:[0.,0.,0.])
 for lat,lon,value in pop:
  if not(BBOX[0]<=lon<=BBOX[2] and BBOX[1]<=lat<=BBOX[3]):continue
  key=(int((lat-BBOX[1])/.012),int((lon-BBOX[0])/.012))
  grid[key]+=value;v=points[key];v[0]+=lat*value;v[1]+=lon*value;v[2]+=value
 for p in poi:
  x,y=p["geometry"]["coordinates"][:2]
  key=(int((y-BBOX[1])/.012),int((x-BBOX[0])/.012))
  grid[key]+=6
 ranking=sorted(grid,key=grid.get,reverse=True)
 chosen=[]
 for k in ranking:
  if points[k][2]<=0:continue
  lat=points[k][0]/points[k][2];lon=points[k][1]/points[k][2]
  if all(math.hypot((lat-p[0])*111000,(lon-p[1])*104000)>950 for p in chosen):
   chosen.append((lat,lon))
  if len(chosen)>=12:break
 return chosen
def preproject(walk,pop,poi,max_snap=60):
 # Project once for all route combinations to prevent repeat STRtree work.
 cells=[];places=[]
 for lat,lon,value in pop:
  if BBOX[0]<=lon<=BBOX[2] and BBOX[1]<=lat<=BBOX[3] and value>0:
   cells.append((walk.snap(lat,lon,max_snap),value))
 for p in poi:
  x,y=p["geometry"]["coordinates"][:2]
  places.append((walk.snap(y,x,max_snap),1))
 return cells,places
def reached(walk,stop_coords,projected,radius=500,max_snap=60):
 seeds,sources=walk.sources(stop_coords,max_snap)
 if not seeds:return set()
 # Nonuniform source distances: same technique as original validated baseline.
 root="__source__";graph=walk.g.copy()
 for node,cost in seeds.items():graph.add_edge(root,node,length=cost)
 d=nx.single_source_dijkstra_path_length(graph,root,weight="length",cutoff=radius+max_snap)
 same=defaultdict(list)
 for gap,u,v,k,length,f,idx in sources:same[idx].append((gap,f))
 result=set()
 for i,(hit,weight) in enumerate(projected):
  if hit is None:continue
  gap,u,v,k,length,f,idx=hit
  best=d.get(u,float("inf"))+f*length
  if walk.g.has_edge(v,u):best=min(best,d.get(v,float("inf"))+(1-f)*length)
  for srcgap,sf in same.get(idx,[]):
   if sf<=f:best=min(best,srcgap+(f-sf)*length)
   elif walk.g.has_edge(v,u):best=min(best,srcgap+(sf-f)*length)
  if gap+best<=radius:result.add(i)
 return result
def totals(indices,cells):
 return round(sum(cells[i][1] for i in indices))
def rank_combos(routes,base_id="L1"):
 base=routes[base_id];base_pop=base["pop_set"];base_poi=base["poi_set"]
 candidates=[r for r in routes if r!=base_id]
 singles=[]
 for key in candidates:
  r=routes[key];p=r["pop_set"]-base_pop;q=r["poi_set"]-base_poi
  singles.append((key,p,q))
 # Note that 2 route optimization uses union, not sum of marginal values.
 combos=[(x,) for x in candidates]+list(itertools.combinations(candidates,2))
 return combos

def evaluate(drive,walk,pop,pois,l1,max_candidates=24,max_snap=60):
 anchor=anchor_points(drive,pop,pois)
 road_nodes=nearest_drive(drive,anchor)
 selected={}
 attempts=0
 for i,j in itertools.combinations(range(len(road_nodes)),2):
  attempts+=1
  try:r=route(drive,road_nodes[i],road_nodes[j])
  except (nx.NetworkXNoPath,nx.NodeNotFound):continue
  if not(4<=r["round_trip_km"]<=22):continue
  signature=tuple(round(v,3) for v in [r["forward_km"],r["reverse_km"]])
  if signature in [v["_sig"] for v in selected.values()]:continue
  r["_sig"]=signature
  selected[f"C{i:02d}-{j:02d}"]=r
  if len(selected)>=max_candidates:break
 w=Network(walk);pop_cells,poi_cells=preproject(w,pop,pois,max_snap)
 routes={"L1":{"stops":l1,"round_trip_km":None,"forward_km":None,"reverse_km":None,"turns_verified":False}}
 routes.update(selected)
 for r in routes.values():
  r["pop_set"]=reached(w,r["stops"],pop_cells,max_snap=max_snap)
  r["poi_set"]=reached(w,r["stops"],poi_cells,max_snap=max_snap)
 base=routes["L1"];basep=base["pop_set"];baseq=base["poi_set"]
 trials=[]
 for cid,r in routes.items():
  res=totals(r["pop_set"],pop_cells);poi=len(r["poi_set"])
  trials.append({"id":cid,"residents":res,"poi":poi,"incremental_residents_vs_L1":totals(r["pop_set"]-basep,pop_cells),
   "incremental_poi_vs_L1":len(r["poi_set"]-baseq),"round_trip_km":r["round_trip_km"],
   "stops":len(r["stops"]),"turns_verified":False})
 combinations=[]
 ids=[x for x in routes if x!="L1"]
 for size in (1,2):
  for subset in itertools.combinations(ids,size):
   picked=[routes["L1"]]+[routes[k] for k in subset]
   pp=set().union(*(r["pop_set"] for r in picked))
   qq=set().union(*(r["poi_set"] for r in picked))
   km=sum(r["round_trip_km"] for r in picked[1:])
   gain=totals(pp-basep,pop_cells)
   poi_gain=len(qq-baseq)
   # Transparent heuristic only, not passengers: infrastructure costs proxy for corridor km.
   score=round(gain+35*poi_gain-180*km,2)
   combinations.append({"routes":["L1",*subset],"covered_residents":totals(pp,pop_cells),
    "covered_poi":len(qq),"incremental_residents":gain,"incremental_poi":poi_gain,
    "new_round_trip_km":round(km,2),"heuristic_score":score,"operationally_validated":False})
 combinations.sort(key=lambda x:x["heuristic_score"],reverse=True)
 trials.sort(key=lambda x:x["incremental_residents_vs_L1"],reverse=True)
 return {"metadata":{"method":"road directed shortest outbound and return; walking-edge access; exhaustive 1-2 complement union search over filtered candidate routes",
   "limitations":["No turn restrictions beyond road graph direction; U-turns/medians/terminal maneuvers NOT validated",
    "Coverage is walking to any proposed stop, NOT access to chosen destinations via timed transfers",
    "POI record counts not deduplicated or trip-weighted; synthetic routes not existing transit",
    "Not observed OD, no timetable, capacity, operating cost or demand estimates",
    "Heuristic score arbitrary; not an economic or travel-time optimum"],
   "walk_snap_tolerance_m":max_snap,"walking_radius_m":500,"anchor_count":len(anchor),"pairs_attempted":attempts,
   "candidates":len(selected),"base_residents":totals(basep,pop_cells),"base_poi":len(baseq)},
   "competitors":trials,"network_combinations":combinations[:30],
   "routes_geojson":{"type":"FeatureCollection","features":[{
    "type":"Feature","properties":{"id":key,"turns_verified":False,"round_trip_km":r["round_trip_km"]},
    "geometry":{"type":"MultiPoint","coordinates":[[p[1],p[0]] for p in r["stops"]]}}
    for key,r in routes.items()]}}
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",default=str(ROOT));ap.add_argument("--max-candidates",type=int,default=18)
 a=ap.parse_args();p=Path(a.root)
 drive=ox.load_graphml(p/"drive.graphml");walk=ox.load_graphml(p/"walk.graphml")
 pop=json.loads((p/"population.json").read_text())["cells"]
 pois=json.loads((p/"destinations.geojson").read_text())["features"]
 f=json.loads((p/"initial_route.geojson").read_text())
 l1=[[q["geometry"]["coordinates"][1],q["geometry"]["coordinates"][0]] for q in f["features"] if q["geometry"]["type"]=="Point"]
 report=evaluate(drive,walk,pop,pois,l1,max_candidates=a.max_candidates)
 routes=report.pop("routes_geojson")
 (p/"discovered_routes.geojson").write_text(json.dumps(routes,separators=(",",":")))
 (p/"route_competition.json").write_text(json.dumps(report,indent=2))
 print(json.dumps({"meta":report["metadata"],"best_competitors":report["competitors"][:5],
 "best_networks":report["network_combinations"][:5]},indent=2))
if __name__=="__main__":main()
