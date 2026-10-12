from pathlib import Path
import json, urllib.request, urllib.parse
root=Path(__file__).resolve().parent
# OSM Overpass: map labels and street attributes, not an engineering survey.
q='[out:json][timeout:35];way["highway"~"^(primary|secondary|tertiary|residential|unclassified|living_street)$"](19.740,-70.752,19.836,-70.620);out geom;'
data=None
for endpoint in ("https://overpass.kumi.systems/api/interpreter","https://overpass-api.de/api/interpreter"):
    try:
        req=urllib.request.Request(endpoint,data=urllib.parse.urlencode({"data":q}).encode(),headers={"User-Agent":"PuertoPlataTransitResearch/0.1 (public open-source prototype)"})
        with urllib.request.urlopen(req,timeout=55) as f:data=json.load(f)
        if "elements" in data:break
    except Exception as e:print("Overpass failed",endpoint,type(e).__name__)
features=[]
if data:
    for w in data["elements"]:
        if w.get("type")!="way" or len(w.get("geometry",[]))<2:continue
        tag=w.get("tags",{})
        coordinates=[[p["lon"],p["lat"]] for p in w["geometry"]]
        features.append({"type":"Feature","properties":{"osm_id":w["id"],"name":tag.get("name") or "Vía sin nombre","highway":tag.get("highway","unknown"),"oneway":tag.get("oneway","unknown"),"lanes":tag.get("lanes","unknown"),"width":tag.get("width","unknown"),"maxwidth":tag.get("maxwidth","unknown"),"bus":tag.get("bus","unknown")},"geometry":{"type":"LineString","coordinates":coordinates}})
obj={"type":"FeatureCollection","metadata":{"provider":"OpenStreetMap via Overpass","source":"https://www.openstreetmap.org/copyright","retrieved":bool(features),"limitations":"Missing lane, width or oneway tags are unknown, not evidence of permissibility. Always field check."},"features":features}
(root/"roads.geojson").write_text(json.dumps(obj,separators=(",",":")))
print("road segments available",len(features))
