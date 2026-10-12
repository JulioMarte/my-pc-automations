"""Inventario y mediciones trazables de calzadas; no inventa anchos faltantes.

Standard library only. GeoJSON EPSG:4326; metric computation uses local
equirectangular projection for short sections, not for surveyed engineering.
"""
import argparse, csv, hashlib, json, math
from pathlib import Path

WGS84_M_PER_DEGREE = 111195.0
REQUIRED = ("segment_id","left_lon","left_lat","right_lon","right_lat","source","source_date","source_license","review_status")

def width_between(a,b):
    lat=math.radians((a[1]+b[1])/2)
    return math.hypot((a[0]-b[0])*WGS84_M_PER_DEGREE*math.cos(lat),
                      (a[1]-b[1])*WGS84_M_PER_DEGREE)

def validate_sample(s):
    missing=[k for k in REQUIRED if s.get(k) in (None,"")]
    if missing: raise ValueError("Missing fields: "+",".join(missing))
    if s["review_status"] not in ("unreviewed","visually_reviewed","field_measured"):
        raise ValueError("Unsupported review_status")
    try:
        a=(float(s["left_lon"]),float(s["left_lat"]))
        b=(float(s["right_lon"]),float(s["right_lat"]))
    except (TypeError, ValueError) as exc: raise ValueError("Invalid geographic coordinates") from exc
    if not all(math.isfinite(x) for x in a+b): raise ValueError("Non-finite coordinates")
    if not all(-180<=p[0]<=180 and -90<=p[1]<=90 for p in (a,b)): raise ValueError("Out of range")
    w=width_between(a,b)
    if not 0.5<=w<=60: raise ValueError("Implausible cross-section width")
    uncertainty=s.get("uncertainty_m")
    if uncertainty in (None,""): uncertainty=None
    else:
        uncertainty=float(uncertainty)
        if not math.isfinite(uncertainty) or uncertainty<0: raise ValueError("Invalid uncertainty")
    if s["review_status"]=="field_measured" and uncertainty is None:
        raise ValueError("Field measurements require uncertainty")
    return {"segment_id":str(s["segment_id"]),"width_m":round(w,3),
            "uncertainty_m":uncertainty,"source":s["source"],
            "source_date":s["source_date"],"source_license":s["source_license"],
            "review_status":s["review_status"],"geometry":{"type":"LineString","coordinates":[list(a),list(b)]},
            "accepted_for_bus":False}

def inventory(features):
    total=0
    counts={"width":0,"est_width":0,"lanes":0,"maxwidth":0,"unknown":0}
    for f in features:
        if f.get("geometry",{}).get("type") not in ("LineString","MultiLineString"): continue
        total+=1
        props=f.get("properties") or {}
        keys={k for k,v in props.items() if v is not None and str(v).strip()!=""}
        for k in ("width","est_width","lanes","maxwidth"):
            if k in keys: counts[k]+=1
        if "width" not in keys: counts["unknown"]+=1
    return {"road_features":total,"tag_counts":counts,
            "note":"OSM width, est_width and maxwidth are distinct; no missing widths imputed"}

def build_report(roads,samples,source_manifest):
    observed=[validate_sample(s) for s in samples]
    if len({(s["segment_id"],tuple(map(tuple,s["geometry"]["coordinates"]))) for s in observed})!=len(observed):
        raise ValueError("Duplicate cross-sections")
    status="NO_MEASUREMENTS_LICENSED_OR_REVIEWED"
    if observed: status="PRELIMINARY_WIDTHS_NOT_BUS_APPROVED"
    return {"schema_version":1,"status":status,"roads":inventory(roads),
            "measurements":observed,"measurements_count":len(observed),
            "license_manifest":source_manifest,"vehicle":"Yutong ZK6126HG",
            "turn_circle_reference_m":20.5,"geometry_approved":False,
            "limitations":["No image-derived widths unless explicitly provided as audited samples",
              "No swept path or curb clearance inferred from point-only route geometries",
              "All 10/20/30 fleet optimizations remain exploratory"]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--roads",type=Path,required=True)
    p.add_argument("--samples",type=Path)
    p.add_argument("--sources",type=Path)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    roads=json.loads(a.roads.read_text(encoding="utf8"))["features"]
    samples=list(csv.DictReader(a.samples.open(encoding="utf8",newline=""))) if a.samples else []
    sources=json.loads(a.sources.read_text(encoding="utf8")) if a.sources else []
    result=build_report(roads,samples,sources)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf8")
    print(json.dumps({"status":result["status"],"roads":result["roads"]["road_features"],"measurements":len(samples)}))

if __name__=="__main__":main()
