"""Local r5py walking / transit accessibility matrices for Puerto Plata.

Requires an OSM .pbf and optionally GTFS.zip, not OSMnx GraphML.
Does not fabricate routes, transit schedules, real passenger demand, or transfers.
"""
from __future__ import annotations
import argparse,datetime as dt,json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def points_from_worldpop(path,limit=80):
 data=json.loads(Path(path).read_text())["cells"]
 cells=[(lat,lon,value) for lat,lon,value in data
        if 19.740<=lat<=19.836 and -70.752<=lon<=-70.620 and value>0]
 cells.sort(key=lambda r:r[2],reverse=True)
 return [{"id":f"O{i:03d}","lat":x[0],"lon":x[1],"population":x[2]}
         for i,x in enumerate(cells[:limit])]
def points_from_pois(path,limit=80):
 data=json.loads(Path(path).read_text())["features"]
 seen=set();out=[]
 for f in data:
  if f.get("geometry",{}).get("type")!="Point":continue
  lon,lat=f["geometry"]["coordinates"][:2]
  typ=f.get("properties",{}).get("type","other")
  key=(round(lat,4),round(lon,4),typ)
  if key in seen:continue
  seen.add(key)
  out.append({"id":f"D{len(out):03d}","lat":lat,"lon":lon,"type":typ})
  if len(out)>=limit:break
 return out
def gdf(points):
 import geopandas as gpd
 from shapely.geometry import Point
 return gpd.GeoDataFrame([{"id":p["id"],"geometry":Point(p["lon"],p["lat"])} for p in points],crs="EPSG:4326")
def summarize_matrix(rows,origins,thresholds=(15,30,45)):
 by_origin={}
 for row in rows:
  key=str(row["from_id"])
  t=row.get("travel_time")
  if t is None:continue
  try:t=float(t)
  except (ValueError,TypeError):continue
  if t<0:continue
  by_origin.setdefault(key,[]).append(t)
 pop_by_id={x["id"]:x.get("population",1) for x in origins}
 total=sum(pop_by_id.values())
 averages={}
 for limit in thresholds:
  reachable=sum(pop_by_id.get(origin,0) for origin,times in by_origin.items() if any(t<=limit for t in times))
  averages[str(limit)]={"population_with_at_least_one_destination":round(reachable,2),
      "share_of_modelled_origin_population":round(reachable/total,4) if total else None}
 return {"thresholds_minutes":averages,"matrix_od_pairs":len(rows),
  "interpretation":"At least one destination reachable; NOT percent of residents who would ride transit",
  "unreachable_origin_count":sum(x["id"] not in by_origin for x in origins)}
def run(network,origin_points,destination_points,departure,modes,matrix_cls):
 import r5py
 allowed={"walk":r5py.TransportMode.WALK,"transit":r5py.TransportMode.TRANSIT}
 if any(m not in allowed for m in modes):raise ValueError("Unknown mode")
 matrix=matrix_cls(network,origins=gdf(origin_points),destinations=gdf(destination_points),
                   departure=departure,transport_modes=[allowed[m] for m in modes],snap_to_network=True)
 return matrix[["from_id","to_id","travel_time"]].to_dict("records")
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--osm-pbf",type=Path,required=True)
 p.add_argument("--gtfs",action="append",default=[],help="Local, dated, validated GTFS ZIP; repeat for multiple networks")
 p.add_argument("--population",type=Path,default=ROOT/"population.json")
 p.add_argument("--destinations",type=Path,default=ROOT/"destinations.geojson")
 p.add_argument("--departure",default="2026-10-14T08:00:00")
 p.add_argument("--max-origins",type=int,default=80)
 p.add_argument("--max-destinations",type=int,default=80)
 p.add_argument("--output",type=Path,default=ROOT/"r5_accessibility.json")
 args=p.parse_args()
 if not args.osm_pbf.is_file():p.error("OSM PBF not found")
 if any(not Path(g).is_file() for g in args.gtfs):p.error("GTFS file missing")
 if min(args.max_origins,args.max_destinations)<=0:p.error("Invalid limits")
 try:departure=dt.datetime.fromisoformat(args.departure)
 except ValueError:p.error("Invalid departure datetime")
 import r5py
 origins=points_from_worldpop(args.population,args.max_origins)
 destinations=points_from_pois(args.destinations,args.max_destinations)
 if not origins or not destinations:p.error("Missing origins or destinations")
 network=r5py.TransportNetwork(args.osm_pbf,args.gtfs)
 modes=["walk","transit"] if args.gtfs else ["walk"]
 rows=run(network,origins,destinations,departure,modes,r5py.TravelTimeMatrix)
 report={"backend":"r5py local R5","osm_pbf":str(args.osm_pbf),"gtfs":args.gtfs,
   "departure":departure.isoformat(),"modes":modes,"origin_count":len(origins),
   "destination_count":len(destinations),"results":summarize_matrix(rows,origins),
   "warnings":["No verified GTFS means walking-only accessibility, not bus performance",
      "WorldPop centroids and Overture POIs are approximate and may contain geographic bias",
      "The 80 origins are the largest population cells: not a representative citywide sample",
      "No sidewalk safety, actual stop access, congestion or physically verified turning geometry",
      "GTFS must actually operate on the specified date for transit comparison"],
   "matrix":rows}
 args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
 print("r5py",modes,"OD pairs",len(rows),"output",args.output)
if __name__=="__main__":main()
