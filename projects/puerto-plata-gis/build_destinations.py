"""Extrae destinos de Puerto Plata de Overture Maps Places (datos reutilizables).
No incluye Google Places: las restricciones de almacenamiento y mapas son diferentes.
"""
import json,subprocess,sys
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parent
BOX="-70.752,19.740,-70.620,19.836"
SRC=ROOT/"overture_raw.geojson"
OUT=ROOT/"destinations.geojson"
SUMMARY=ROOT/"destinations_report.json"

CATEGORIES={
 "health":("hospital","clinic","medical","doctor","dentist","pharmacy","health"),
 "education":("school","college","university","kindergarten","education","training"),
 "retail":("supermarket","shopping","mall","department_store","grocery","retail","market","store"),
 "jobs":("business","office","factory","industrial","warehouse","government","bank"),
 "recreation":("park","sports","stadium","museum","cinema","theater","beach","recreation","fitness"),
 "lodging":("hotel","resort","hostel","lodging"),
 "transport":("bus_station","transport","terminal","station","airport"),
}
WEIGHTS={"health":5,"education":5,"retail":4,"jobs":3,"recreation":2,"lodging":2,"transport":4,"other":1}

def category(raw):
    s=str(raw or "").lower()
    for group,words in CATEGORIES.items():
        if any(w in s for w in words):return group
    return "other"

def name_of(props):
    names=props.get("names") or {}
    if isinstance(names,str):
        try:names=json.loads(names)
        except ValueError:names={}
    if isinstance(names,dict):
        return names.get("primary") or names.get("common",{}).get("es")
    return None

def main():
    if not SRC.exists():
        cmd=["overturemaps","download","--bbox",BOX,"-f","geojson","--type","place","-o",str(SRC)]
        print("Requesting Overture data for",BOX,flush=True)
        subprocess.run(cmd,check=True,timeout=600)
    features=[];counts=Counter();missing=0
    with SRC.open(encoding="utf-8") as fh:
        for line in fh:
            line=line.strip()
            if not line:continue
            obj=json.loads(line)
            entries=obj.get("features",[]) if obj.get("type")=="FeatureCollection" else [obj]
            for f in entries:
                if f.get("type")!="Feature" or f.get("geometry",{}).get("type")!="Point":continue
                p=f.get("properties") or {}
                n=name_of(p)
                if not n:missing+=1;continue
                coords=f["geometry"].get("coordinates") or []
                if len(coords)<2 or not(-70.752<=coords[0]<=-70.620 and 19.740<=coords[1]<=19.836):continue
                raw=p.get("basic_category") or ""
                kind=category(raw)
                if kind=="other":continue
                counts[kind]+=1
                features.append({"type":"Feature","geometry":f["geometry"],"properties":{
                    "name":str(n)[:150],"type":kind,"overture_category":str(raw)[:120],
                    "weight_candidate":WEIGHTS[kind],"provider":"Overture Maps",
                    "overture_id":str(p.get("id") or f.get("id") or "")}})
    if not features:raise RuntimeError("No classified POIs returned; refuse empty output")
    collection={"type":"FeatureCollection","metadata":{"bbox_wsen":BOX,
        "provider":"Overture Maps Places","license":"CDLA-Permissive 2.0 / Apache 2.0; verify upstream source notices",
        "meaning":"POI locations are candidate destinations, NOT observed passenger demand",
        "caution":"Coverage, freshness, category and exact pedestrian entrance are not field-verified"},
        "features":features}
    OUT.write_text(json.dumps(collection,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    summary={"bbox_wsen":BOX,"classified":len(features),"categories":dict(counts),"skipped_without_name":missing,
        "source":"Overture Maps Places; current public release"}
    SUMMARY.write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(summary,indent=2),flush=True)

if __name__=="__main__":main()
