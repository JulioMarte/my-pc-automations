"""Climate factor baseline from NASA POWER climatology (point, not street-level).
This produces descriptive weather context rather than fabricated ridership forecasts.
"""
import json,urllib.parse,urllib.request,argparse
from pathlib import Path

ROOT=Path(__file__).resolve().parent
POINTS={"centro":(19.796,-70.694),"oeste":(19.791,-70.73),"este":(19.76,-70.647)}
PARAMS="T2M,T2M_MAX,RH2M,PRECTOTCORR"
def request(lat,lon):
 q=urllib.parse.urlencode({"parameters":PARAMS,"community":"RE","longitude":lon,
 "latitude":lat,"format":"JSON"})
 url="https://power.larc.nasa.gov/api/temporal/climatology/point?"+q
 req=urllib.request.Request(url,headers={"User-Agent":"PuertoPlataGIS-research/0.3"})
 with urllib.request.urlopen(req,timeout=65) as response:
  data=json.load(response)
 values=data.get("properties",{}).get("parameter",{})
 for p in ("T2M","T2M_MAX","RH2M","PRECTOTCORR"):
  if p not in values or not isinstance(values[p],dict):raise RuntimeError("Missing NASA POWER variable "+p)
  if not any(k in values[p] for k in ("JAN","ANN")):raise RuntimeError("No climatology months "+p)
 return {"position":{"lat":lat,"lon":lon},"parameters":values,"url":url}
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--output",default=str(ROOT/"climate_context.json"));a=ap.parse_args()
 out={"source":"NASA POWER climatology API","resolution":"point-based atmospheric model; NOT sidewalk microclimate",
  "cautions":["Monthly climate normals, not hourly observations","Heat exposure varies with trees, sun, humidity, shade and bus stops",
  "Do not infer demand or stop placements from coarse climate points"],"locations":{}}
 for name,(lat,lon) in POINTS.items():out["locations"][name]=request(lat,lon)
 Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
 print(json.dumps({x:{"T2M_annual":z["parameters"]["T2M"].get("ANN"),"T2M_MAX_annual":z["parameters"]["T2M_MAX"].get("ANN")} for x,z in out["locations"].items()},indent=2))
if __name__=="__main__":main()
