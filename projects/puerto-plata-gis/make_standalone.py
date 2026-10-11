from pathlib import Path
import json
root=Path(__file__).resolve().parent
html=(root/"index.html").read_text(encoding="utf-8")
population=json.loads((root/"population.json").read_text(encoding="utf-8"))
route=json.loads((root/"initial_route.geojson").read_text(encoding="utf-8"))
roads=json.loads((root/"roads.geojson").read_text(encoding="utf-8"))
payload="<script>window.__POPULATION__="+json.dumps(population,separators=(",",":"))+";window.__INITIAL_ROUTE__="+json.dumps(route,separators=(",",":"))+";window.__ROADS__="+json.dumps(roads,separators=(",",":"))+";</script>"
assert "</head>" in html
out=html.replace("</head>",payload+"</head>",1)
(root/"Puerto_Plata_Linea_1_Mapa_Interactivo.html").write_text(out,encoding="utf-8")
assert "window.__POPULATION__" in out
assert "window.__INITIAL_ROUTE__" in out
print("Standalone HTML bytes:",len(out.encode("utf-8")))
