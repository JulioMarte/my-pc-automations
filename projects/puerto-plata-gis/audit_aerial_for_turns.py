"""Audit real STAC candidate imagery for nine unverified Yutong turn points.

Bounding boxes indicate possible coverage only, NOT actual valid pixels.
Never approves imagery for road-width measurements without independent raster
inspection, image rights and horizontal accuracy.
"""
import argparse, datetime, json, math
from pathlib import Path

ALLOWED_LICENSES={"CC-BY-4.0","CC-BY-SA-4.0"}
REQUIRED_GSD_M=0.30
MAX_IMAGE_AGE_YEARS=3

def bbox_contains(bbox,lon,lat):
    return isinstance(bbox,list) and len(bbox)==4 and all(isinstance(a,(float,int)) and math.isfinite(a) for a in bbox) and bbox[0]<=lon<=bbox[2] and bbox[1]<=lat<=bbox[3]

def evaluate(images,queue,as_of="2026-10-11"):
    if queue.get("status")!="UNVERIFIED_FIELD_SURVEY_QUEUE":
        raise ValueError("Expected unresolved field survey queue")
    today=datetime.date.fromisoformat(as_of)
    rows=[]
    for task in queue["risks"]:
        lon,lat=task["longitude"],task["latitude"]
        matches=[]
        for entry in images:
            if not bbox_contains(entry.get("bbox"),lon,lat):continue
            date=(entry.get("datetime") or "")[:10]
            try:years=(today-datetime.date.fromisoformat(date)).days/365.2425
            except ValueError:years=None
            gsd=entry.get("gsd_m_reported")
            license_name=entry.get("license_reported")
            problems=[]
            if license_name not in ALLOWED_LICENSES:problems.append("LICENSE_NOT_VERIFIED_FOR_UNRESTRICTED_USE")
            if not isinstance(gsd,(int,float)) or not math.isfinite(gsd) or gsd>REQUIRED_GSD_M:problems.append("GSD_NOT_SUFFICIENT_FOR_PRECISION_PILOT")
            if years is None or years>MAX_IMAGE_AGE_YEARS:problems.append("HISTORICAL_IMAGE")
            problems.extend(["VALID_PIXEL_FOOTPRINT_UNCHECKED","CURB_VISIBILITY_UNCHECKED","HORIZONTAL_ACCURACY_UNVERIFIED","RASTER_NOT_INSPECTED"])
            matches.append({"id":entry.get("id"),"gsd_m":gsd,"acquired":date or None,
                            "age_years":round(years,1) if years is not None else None,
                            "license":license_name,"asset_types":entry.get("asset_types",[]),
                            "bbox_intersection_only":True,"blockers":problems,
                            "fit_for_width_measurement":False})
        matches.sort(key=lambda x:(x["age_years"] if x["age_years"] is not None else 1000,x["gsd_m"] or 1000))
        rows.append({"candidate":task["candidate"],"latitude":lat,"longitude":lon,
                     "heading_change_deg":task["heading_change_deg"],
                     "catalog_bbox_matches":len(matches),"matches":matches,
                     "width_measurement_status":"BLOCKED",
                     "suggested_next_source":"LICENSED_RECENT_ORTHOPHOTO_OR_GROUND_SURVEY"})
    return {"status":"COVERAGE_SCREENED_NO_VALID_ROAD_WIDTH_IMAGERY",
            "assessed_turns":len(rows),
            "turns_with_catalog_bbox_overlap":sum(bool(x["matches"]) for x in rows),
            "fit_for_precision_measurements":0,
            "max_accepted_gsd_m":REQUIRED_GSD_M,"max_age_years":MAX_IMAGE_AGE_YEARS,
            "limitations":["STAC bbox overlap does not prove valid imagery pixels","Pixel GSD is not horizontal positional accuracy","Images are not geometrically aligned or visually inspected","Unresolved license/rights must be checked for each actual raster","No road turn or width is approved"],
            "turns":rows}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--catalog",type=Path,required=True)
    p.add_argument("--turns",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    catalog=json.loads(args.catalog.read_text(encoding="utf-8"))
    survey=json.loads(args.turns.read_text(encoding="utf-8"))
    if catalog.get("status")!="DISCOVERED_UNVERIFIED_IMAGES":
        raise RuntimeError("No confirmed live image catalog evidence to audit")
    result=evaluate(catalog["images"],survey)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":result["status"],"turns":result["assessed_turns"],
                      "bbox_matched":result["turns_with_catalog_bbox_overlap"],
                      "usable_images":result["fit_for_precision_measurements"]}))
if __name__=="__main__":main()
