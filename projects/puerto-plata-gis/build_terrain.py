"""Sample Mapzen/Tilezen Terrarium terrain elevation at candidate stops.

Data resolution depends on tile zoom/source. Not survey-grade slope data,
not pedestrian sidewalk gradient, and never validates bus turning geometry.
"""
import io,math,json,urllib.request,argparse
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parent
def tile(lat,lon,z):
 lat=max(-85.0511,min(85.0511,lat))
 n=2**z; x=(lon+180)/360*n
 y=(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n
 return int(x),int(y),int((x%1)*256),int((y%1)*256)
def height(pixel):
 return pixel[0]*256+pixel[1]+pixel[2]/256-32768
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--route",default=str(ROOT/"initial_route.geojson"))
 ap.add_argument("--output",default=str(ROOT/"terrain_stops.json"));ap.add_argument("--zoom",type=int,default=12)
 a=ap.parse_args()
 if a.zoom<8 or a.zoom>14:raise ValueError("zoom must be 8..14")
 fc=json.loads(Path(a.route).read_text());stops=[f for f in fc["features"] if f["geometry"]["type"]=="Point"]
 cache={};rows=[]
 for i,f in enumerate(stops):
  lon,lat=f["geometry"]["coordinates"][:2];tx,ty,px,py=tile(lat,lon,a.zoom)
  key=(tx,ty)
  if key not in cache:
   url=f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{a.zoom}/{tx}/{ty}.png"
   req=urllib.request.Request(url,headers={"User-Agent":"PuertoPlataGIS/0.3"})
   with urllib.request.urlopen(req,timeout=40) as r:data=r.read()
   cache[key]=Image.open(io.BytesIO(data)).convert("RGB")
  m=round(height(cache[key].getpixel((px,py))),2)
  rows.append({"stop_index":i+1,"lat":lat,"lon":lon,"height_m_approx":m})
 out={"provider":"Mapzen/Tilezen Terrain Tiles public AWS dataset","zoom":a.zoom,
  "classification":"exploratory ground elevation estimate; NOT accessibility-validated gradient",
  "cautions":["Tile elevation can miss sidewalks, ramps and curb heights",
  "Terrain elevation does not describe median crossings or turn radii",
  "No passenger demand or walking heat exposure can be inferred from this alone"],"stops":rows}
 Path(a.output).write_text(json.dumps(out,indent=2))
 print("Terrain sampled for",len(rows),"L1 provisional stops",len(cache),"tiles")
if __name__=="__main__":main()
