"""Network walking accessibility for proposed transit stops.

Projected segment snap via STRtree; partial edge distances via a directed
graph and same-edge direct traversal. Treat OSM walkways as possible paths,
not verified sidewalk/crossing infrastructure.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import networkx as nx
import osmnx as ox
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parent
METRES_PER_DEG_LAT=111195.0

def xy(lat,lon,lat0):
 return lon*METRES_PER_DEG_LAT*math.cos(math.radians(lat0)),lat*METRES_PER_DEG_LAT

class Network:
 def __init__(self,g):
  self.g=g
  self.lat0=sum(d["y"] for _,d in g.nodes(data=True))/len(g)
  self.segments=[]
  self.geoms=[]
  for u,v,k,d in g.edges(keys=True,data=True):
   if u==v or float(d.get("length",0))<=0:continue
   geom=d.get("geometry")
   pts=list(geom.coords) if geom is not None else [(g.nodes[u]["x"],g.nodes[u]["y"]),(g.nodes[v]["x"],g.nodes[v]["y"])]
   if math.dist(pts[0],(g.nodes[u]["x"],g.nodes[u]["y"]))>math.dist(pts[-1],(g.nodes[u]["x"],g.nodes[u]["y"])):pts.reverse()
   line=LineString([xy(y,x,self.lat0) for x,y in pts])
   if line.length<0.001:continue
   self.segments.append((u,v,k,float(d["length"])))
   self.geoms.append(line)
  if not self.geoms:raise ValueError("Walking graph has no usable geometry")
  self.tree=STRtree(self.geoms)
 def snap(self,lat,lon,max_snap):
  point=Point(*xy(lat,lon,self.lat0))
  idx=int(self.tree.nearest(point))
  line=self.geoms[idx]
  gap=point.distance(line)
  if gap>max_snap:return None
  u,v,k,length=self.segments[idx]
  fraction=line.project(point)/line.length
  return (gap,u,v,k,length,fraction,idx)
 def sources(self,stops,max_snap):
  seeds={};projections=[]
  for lat,lon in stops:
   hit=self.snap(lat,lon,max_snap)
   if hit is None:continue
   gap,u,v,k,length,f,idx=hit
   projections.append(hit)
   seeds[v]=min(seeds.get(v,float("inf")),gap+(1-f)*length)
   # Reverse travel is allowed only if a matching reverse directed edge exists.
   if self.g.has_edge(v,u):
    seeds[u]=min(seeds.get(u,float("inf")),gap+f*length)
  return seeds,projections

def coverage(g,stops,cells,radius=500,max_snap=120):
 if radius<=0 or max_snap<0:raise ValueError("Invalid cutoff")
 idx=Network(g)
 seeds,source_pts=idx.sources(stops,max_snap)
 if not seeds:raise ValueError("No stops snapped to mapped pedestrian network")
 # Multi-source shortest distance with nonuniform source costs.
 aux=g.copy();root="__TRANSIT_COVERAGE_ORIGIN__"
 for node,cost in seeds.items():aux.add_edge(root,node,length=cost)
 lengths=nx.single_source_dijkstra_path_length(aux,root,weight="length",cutoff=radius+max_snap)
 total=0.;covered=0;excluded=0.;snap_coverage=0
 for lat,lon,pop in cells:
  if pop<=0:continue
  hit=idx.snap(lat,lon,max_snap)
  if hit is None:excluded+=pop;continue
  gap,u,v,k,edge_len,f,_=hit
  dist=lengths.get(u,float("inf"))+f*edge_len
  if g.has_edge(v,u):dist=min(dist,lengths.get(v,float("inf"))+(1-f)*edge_len)
  # Both endpoints on same physical directed segment can access one another
  # without first reaching the intersection/node.
  for sgap,su,sv,sk,slen,sf,si in source_pts:
   if si==hit[6]:
    if sf<=f:dist=min(dist,sgap+gap+(f-sf)*edge_len)
    if sf>f and g.has_edge(v,u):dist=min(dist,sgap+gap+(sf-f)*edge_len)
  if gap+dist<=radius:
   total+=pop;covered+=1
 return {"residents":round(total),"covered_cells":covered,
  "excluded_people_due_to_snap":round(excluded),
  "snapped_stops":len(source_pts),"total_stops":len(stops),
  "network_type":"OSMnx walk directed edges","radius_m":radius,"max_snap_m":max_snap,
  "method":"STRtree nearest line, partial edge traversal, directed Dijkstra",
  "caveats":["Snap connectors are assumed walkable; barriers and crossings unverified",
   "Walking graph may contain missing or wrong OSM connections",
   "Nearest directed edge can misrepresent access when carriageways differ",
   "Edge lengths derived from OSM attributes; projected geometry used for fractions",
   "Same-edge direct travel requires shared selected directed segment",
   "WorldPop population is estimated, not a census person count"]}

def main():
 p=argparse.ArgumentParser()
 p.add_argument("--graph",default=str(ROOT/"walk.graphml"))
 p.add_argument("--population",default=str(ROOT/"population.json"))
 p.add_argument("--route",default=str(ROOT/"initial_route.geojson"))
 p.add_argument("--output",default=str(ROOT/"network_access_report.json"))
 a=p.parse_args()
 g=ox.load_graphml(a.graph)
 pop=json.loads(Path(a.population).read_text())["cells"]
 fc=json.loads(Path(a.route).read_text())
 stops=[[f["geometry"]["coordinates"][1],f["geometry"]["coordinates"][0]]
   for f in fc["features"] if f["geometry"]["type"]=="Point"]
 report=coverage(g,stops,pop)
 Path(a.output).write_text(json.dumps(report,indent=2))
 print(json.dumps(report,indent=2))
if __name__=="__main__":main()
