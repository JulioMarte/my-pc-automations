"""Offline data, browser Leaflet visual. No invented travel time or street widths."""
import argparse,json
from pathlib import Path

def render(lines,zones):
    gj=json.dumps(lines,separators=(",",":")).replace("</","<\\/")
    keys=json.dumps(zones,separators=(",",":")).replace("</","<\\/")
    return r'''<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Puerto Plata — líneas de deseo H3 (escenario sintético)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>body{margin:0;font:14px system-ui;background:#e6ecf0}#map{height:calc(100vh - 106px)}
header{padding:13px 19px;background:#173344;color:white}header strong{font-size:17px}
header small{display:block;margin-top:5px}footer{padding:8px 17px;background:white}
</style></head><body>
<header><strong>Puerto Plata · H3 y líneas de deseo</strong>
<small>Demanda gravitacional sintética / WorldPop + Overture / NO aforos ni rutas aprobadas.</small></header>
<div id="map"></div><footer>
Celdas destacadas por flujo de extremos OD; enlaces por línea recta.
Las líneas NO son rutas de autobuses.
</footer><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>const desires=__LINES__;const keyzones=__ZONES__;
const map=L.map('map').setView([19.788,-70.683],12);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
 {maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(map);
const lines=L.geoJSON(desires,{style:f=>({color:'#2879a0',weight:1,opacity:.15})}).addTo(map);
const cells=L.geoJSON(keyzones,{style:f=>({color:'#a93b18',weight:2,
  fillColor:'#f59e4c',fillOpacity:.34}),
 onEachFeature:(f,layer)=>layer.bindPopup(
 'H3 '+f.properties.h3_id+' · Puesto '+f.properties.rank+
 ' · Flujo relativo extremo '+f.properties.endpoint_flow_proxy+
 '<br>Habitantes estimados '+f.properties.residents_estimate+
 '<br>Sin demanda observada ni bordillos medidos')}).addTo(map);
const control=L.control.layers(null,{'Líneas de deseo':lines,'20 celdas clave':cells},
 {collapsed:false}).addTo(map);
map.fitBounds(cells.getBounds().extend(lines.getBounds()));
</script></body></html>'''.replace("__LINES__",gj).replace("__ZONES__",keys)

def main():
    p=argparse.ArgumentParser()
    for n in ("desires","keyzones","output"):p.add_argument("--"+n,type=Path,required=True)
    a=p.parse_args()
    lines=json.loads(a.desires.read_text());zones=json.loads(a.keyzones.read_text())
    if lines.get("type")!="FeatureCollection" or zones.get("type")!="FeatureCollection":
        raise ValueError("Expected georeferenced features")
    a.output.write_text(render(lines,zones),encoding="utf-8")
    print("Synthetic desire line map",len(lines["features"]),"links",len(zones["features"]),"key H3 zones")
if __name__=="__main__":main()
