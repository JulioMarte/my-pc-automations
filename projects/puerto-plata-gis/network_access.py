"""Street-network 500m walk access, with edge projection and partial-edge costs.

Uses OSMnx's directed walk MultiDiGraph; exports diagnostics and no fabricated
precision about sidewalk safety. Uses candidate stop/population coordinates.
"""
import argparse, json, math
from pathlib import Path
import networkx as nx
import osmnx as ox
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parent
METRES_DEG_LAT=111195.0
def xy(lat,lon,lat0):
 return (lon*METRES_DEG_LAT*math.cos(math.radians(lat0)),lat*METRES_DEG_LAT)
def prepare(g,lat0):
 segments=[]
 for u,v,k,d in g.edges(keys=True,data=True):
  if u==v:continue
  length=float(d.get("length",0))
  if length<=0:continue
  # Edge geom may curve; use segment projection along polyline, not only graph intersections.
  geom=d.get("geometry")
  pts=list(geom.coords) if geom is not None else [(g.nodes[u]["x"],g.nodes[u]["y"]),(g.nodes[v]["x"],g.nodes[v]["y"])]
  # OSMnx graph edge geometry generally ordered u->v, but may be reversed.
  if math.dist(pts[0],(g.nodes[u]["x"],g.nodes[u]["y"]))>math.dist(pts[-1],(g.nodes[u]["x"],g.nodes[u]["y"])):pts.reverse()
  p=[xy(y,x,lat0) for x,y in pts]
  lengths=[math.dist(a,b) for a,b in zip(p,p[1:])]
  cum=0;total=sum(lengths)
  for (a,b),sl in zip(zip(p,p[1:]),lengths):
   if sl>0:
    segments.append((a,b,u,v,k,length,cum/total,(cum+sl)/total))
   cum+=sl
 return segments
def project(lat,lon,segments,lat0):
 x,y=xy(lat,lon,lat0)
 best=None
 for a,b,u,v,k,length,f0,f1 in segments:
  dx=b[0]-a[0];dy=b[1]-a[1]
  t=max(0.,min(1.,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
  px=a[0]+t*dx;py=a[1]+t*dy
  d=math.hypot(x-px,y-py)
  if best is None or d<best[0]:best=(d,u,v,k,length,f0+t*(f1-f0))
 return best
def coverage(g,stops,cells,radius=500,max_snap=120):
 lat0=sum(g.nodes[n]["y"] for n in g.nodes)/len(g)
 segs=prepare(g,lat0)
 # Multi-source Dijkstra on street intersections, partial distances from projected stops.
 seeds={}
 for lat,lon in stops:
  snap=project(lat,lon,segs,lat0)
  if snap is None or snap[0]>max_snap:continue
  offset,u,v,k,length,f=snap
  # Walking source at interior of directed edge. Allow travel along edge toward v;
  # opposite direction only if a real reverse edge exists.
  seeds[v]=min(seeds.get(v,float("inf")),offset+(1-f)*length)
  if g.has_edge(v,u):seeds[u]=min(seeds.get(u,float("inf")),offset+f*length)
 distances=nx.multi_source_dijkstra_path_length(g,seeds.keys(),weight="length",cutoff=radius+max_snap) if seeds else {}
 # multi-source Dijkstra cannot encode unequal start costs: use super source.
 h=g.copy();source="__TRANSIT_SOURCE__"
 for node,cost in seeds.items():h.add_edge(source,node,length=cost)
 distances=nx.single_source_dijkstra_path_length(h,source,weight="length",cutoff=radius+max_snap) if seeds else {}
 total=0;included=0;missing=0
 for lat,lon,pop in cells:
  if pop<=0:continue
  hit=project(lat,lon,segs,lat0)
  if hit is None or hit[0]>max_snap:missing+=pop;continue
  off,u,v,k,length,f=hit
  # Distance from street network to projected destination: directed travel into edge from u.
  net=distances.get(u,float("inf"))+f*length
  # Source and destination on SAME edge (network nodes alone may overestimate).
  direct=min((math.hypot(*[a-b for a,b in zip(xy(lat,lon,lat0),xy(slat,slon,lat0))])
              for slat,slon in stops),default=float("inf"))
  # Direct-distance lower bound alone is NOT a traversable path; do not use it as a route.
  # Handle endpoints by actual graph edges; direct < radius only identifies potential false negatives.
  if off+net<=radius:total+=pop;included+=1
 return {"residents":round(total),"covered_cells":included,"excluded_people_due_to_snap":round(missing),
 "coverage_method":"directed OSM pedestrian graph; projection onto edge + partial directed edge length",
 "limitations":"No verified sidewalks/road crossings; source on same edge can be underestimated or omitted. Snap connector assumes walkability."}
def main():
 p=argparse.ArgumentParser();p.add_argument("--graph",default=str(ROOT/"walk.graphml"));p.add_argument("--population",default=str(ROOT/"population.json"));p.add_argument("--route",default=str(ROOT/"initial_route.geojson"));p.add_argument("--output",default=str(ROOT/"network_access_report.json"))
 a=p.parse_args()
 g=ox.load_graphml(a.graph);pop=json.loads(Path(a.population).read_text())["cells"];fc=json.loads(Path(a.route).read_text())
 stops=[[f["geometry"]["coordinates"][1],f["geometry"]["coordinates"][0]] for f in fc["features"] if f["geometry"]["type"]=="Point"]
 result=coverage(g,stops,pop)
 Path(a.output).write_text(json.dumps(result,indent=2))
 print(json.dumps(result,indent=2))
if __name__=="__main__":main()
