"""Exploratory hourly origin-destination (OD) accessibility model.

Inputs: WorldPop estimated resident cells, Overture POIs, proposed L1 stops.
Outputs are opportunity-weighted synthetic accessibility, NOT observed trips.
No claims of passenger forecasts, validated pedestrian access, or bus-safe paths.
"""
from __future__ import annotations
import argparse, json, math, csv
from pathlib import Path
from collections import defaultdict

ROOT=Path(__file__).resolve().parent
PERIOD_WEIGHTS={
 "05:30-06:30":{"jobs":4,"health":1,"education":2,"retail":0.5,"recreation":0.5,"lodging":2,"transport":2},
 "06:30-09:00":{"jobs":5,"health":2,"education":5,"retail":1,"recreation":0.5,"lodging":2,"transport":3},
 "09:00-12:00":{"jobs":2,"health":5,"education":2,"retail":4,"recreation":2,"lodging":2,"transport":2},
 "12:00-14:00":{"jobs":2,"health":3,"education":3,"retail":4,"recreation":3,"lodging":2,"transport":2},
 "14:00-16:30":{"jobs":3,"health":3,"education":3,"retail":4,"recreation":3,"lodging":3,"transport":2},
 "16:30-19:30":{"jobs":4,"health":1,"education":2,"retail":3,"recreation":4,"lodging":4,"transport":3}}
def hav(a,b):
 lat1,lon1=map(math.radians,a);lat2,lon2=map(math.radians,b)
 h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
 return 12742017.6*math.asin(min(1,math.sqrt(h)))
def nearest(p,stops):
 return min((hav(p,s),i) for i,s in enumerate(stops))
def calc(pop,pois,stops,radius=500,max_cells=25000,max_pois=5000):
 if not stops or len(pop)>max_cells or len(pois)>max_pois:raise ValueError("Missing stops or input too large")
 origin=defaultdict(float)
 for cell in pop:
  if not(len(cell)>=3 and cell[2]>0):continue
  d,i=nearest(cell[:2],stops)
  if d<=radius:origin[i]+=cell[2]
 destinations=defaultdict(lambda:defaultdict(int))
 for poi in pois:
  coords=poi["geometry"]["coordinates"]
  p=poi.get("properties") or {}
  kind=p.get("type","other")
  d,i=nearest([coords[1],coords[0]],stops)
  if d<=radius:destinations[i][kind]+=1
 periods=[]
 for period,weights in PERIOD_WEIGHTS.items():
  opportunities={i:sum(count*weights.get(kind,0) for kind,count in group.items()) for i,group in destinations.items()}
  total=sum(opportunities.values())
  pairs=[]
  for i,people in origin.items():
   for j,opp in opportunities.items():
    if i==j or opp<=0:continue
    # Dimensionless, synthetic gravity potential. NOT person trips.
    separation=hav(stops[i],stops[j])
    factor=1/(1+separation/2500)**2
    score=round(people*opp*factor,3)
    if score>0:pairs.append({"origin_stop":i+1,"destination_stop":j+1,
        "weighted_accessibility":score})
  pairs.sort(key=lambda x:x["weighted_accessibility"],reverse=True)
  periods.append({"period":period,"total_destination_opportunity_weight":round(total,2),
    "top_od_pairs":pairs[:30]})
 return {"metadata":{"method":"synthetic opportunity-weighted gravity; not observed OD",
  "walking":"500m Euclidean candidate filter, NOT street walking",
  "route":"L1 outbound only; no validated reverse bus path",
  "units":"weighted_accessibility has arbitrary units; DO NOT interpret as trips",
  "poi_weights":"heuristic time-period category weights, not surveyed activity",
  "population":"WorldPop 2025 model, not census block ground truth"},
  "resident_coverage_estimate":round(sum(origin.values())),
  "origin_by_stop":[{"stop":i+1,"residents":round(x,2)} for i,x in sorted(origin.items())],
  "destinations_by_stop":[{"stop":i+1,"categories":dict(sorted(v.items()))} for i,v in sorted(destinations.items())],
  "periods":periods}
def main():
 a=argparse.ArgumentParser()
 a.add_argument("--population",default=str(ROOT/"population.json"))
 a.add_argument("--destinations",default=str(ROOT/"destinations.geojson"))
 a.add_argument("--route",default=str(ROOT/"initial_route.geojson"))
 a.add_argument("--output",default=str(ROOT/"od_synthetic.json"))
 args=a.parse_args()
 pop=json.loads(Path(args.population).read_text())["cells"]
 poi=json.loads(Path(args.destinations).read_text())["features"]
 fc=json.loads(Path(args.route).read_text())
 stops=[[f["geometry"]["coordinates"][1],f["geometry"]["coordinates"][0]]
   for f in fc["features"] if f["geometry"]["type"]=="Point"]
 result=calc(pop,poi,stops)
 Path(args.output).write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")))
 print(f"OD synthetic: {result['resident_coverage_estimate']} origin residents; {len(result['periods'])} period matrices; {len(stops)} stops")
if __name__=="__main__":main()
