from pathlib import Path
import json
root=Path(__file__).parent
s=(root/"index.html").read_text()
for p in ("satellite","addstop","routeedit","population.json","radius","250","download","leaflet","coverage","Esri"):
    assert p in s,p
if (root/"population.json").exists():
    d=json.loads((root/"population.json").read_text())
    assert d["metadata"]["year"]==2025 and len(d["cells"])>100
print("OK viewer and population data")
