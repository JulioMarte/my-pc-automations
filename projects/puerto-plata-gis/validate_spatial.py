"""CRS and geometry validation for Puerto Plata datasets.

Checks actual transforms to EPSG:32619 and spatial bounds. Projection is performed
during calculation without replacing source WGS84 GeoJSON coordinates.
"""
import argparse,json,math
from pathlib import Path
from pyproj import Transformer,CRS
from shapely.geometry import shape
from shapely.validation import explain_validity

ROOT=Path(__file__).resolve().parent
BBOX=(-70.752,19.740,-70.620,19.836)
def validate(population,destinations,route):
 proj=Transformer.from_crs("EPSG:4326","EPSG:32619",always_xy=True)
 issues=[];all_features=0
 for label,fc in [("destinations",destinations),("route",route)]:
  if fc.get("type")!="FeatureCollection":issues.append(label+": not a FeatureCollection");continue
  for i,f in enumerate(fc["features"]):
   try:
    geom=shape(f["geometry"])
    if geom.is_empty or not geom.is_valid:issues.append(f"{label}[{i}]: {explain_validity(geom)}")
    x,y=geom.representative_point().coords[0]
    e,n=proj.transform(x,y)
    if not(math.isfinite(e) and math.isfinite(n)):issues.append(f"{label}[{i}]: invalid UTM projection")
   except Exception as ex:issues.append(f"{label}[{i}]: {str(ex)[:120]}")
   all_features+=1
 cells=population.get("cells",[])
 if not cells:issues.append("empty population")
 total=0.;inside=0.
 for i,c in enumerate(cells):
  if len(c)!=3:issues.append(f"cell {i} not lat,lon,weight");continue
  lat,lon,weight=c
  if not all(math.isfinite(float(x)) for x in c) or weight<0:issues.append(f"cell {i} invalid");continue
  total+=weight
  if BBOX[0]<=lon<=BBOX[2] and BBOX[1]<=lat<=BBOX[3]:inside+=weight
 if inside<=0:issues.append("population inside study bbox is empty")
 return {"status":"VALIDADO_GEOMETRICAMENTE" if not issues else "INVALIDO",
  "target_crs":"EPSG:32619","source_crs":"EPSG:4326",
  "feature_count":all_features,"population_total":round(total),"population_inside_study_bbox":round(inside),
  "issues":issues[:100],"note":"This is a schema/geometry audit, not a public transport route approval"}
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--root",type=Path,default=ROOT)
 p.add_argument("--output",type=Path,default=ROOT/"spatial_validation.json")
 a=p.parse_args();base=a.root
 report=validate(*[json.loads((base/n).read_text()) for n in ("population.json","destinations.geojson","initial_route.geojson")])
 a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps(report,ensure_ascii=False,indent=2))
 if report["issues"]:raise SystemExit(1)
if __name__=="__main__":main()
