"""Conservative imagery metadata eligibility gate; no imagery acquired here."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

def evaluate(item):
    blockers=[]
    if not item.get("url") and not item.get("local_path"):
        blockers.append("MISSING_IMAGE_LOCATION")
    if not item.get("measurement_rights_confirmed"):
        blockers.append("MEASUREMENT_RIGHTS_UNCONFIRMED")
    if not item.get("coverage_intersects_puerto_plata"):
        blockers.append("COVERAGE_NOT_VERIFIED")
    if not item.get("acquired_at"):
        blockers.append("IMAGE_DATE_UNKNOWN")
    if not item.get("georeferenced"):
        blockers.append("NOT_GEOREFERENCED")
    if not item.get("crs"):
        blockers.append("CRS_UNKNOWN")
    for field,limit in [("gsd_m",0.30),("horizontal_accuracy_m",0.50)]:
        val=item.get(field)
        if not isinstance(val,(int,float)) or not math.isfinite(val) or val<=0:
            blockers.append(field.upper()+"_UNKNOWN")
        elif val>limit:
            blockers.append(field.upper()+"_EXCEEDS_PILOT_THRESHOLD")
    return {"id":item.get("id"),"eligible_for_pilot":not blockers,
            "blockers":blockers,"license":item.get("license"),
            "accuracy_claim":"metadata-only; not independently verified"}

def gate(items):
    result=[evaluate(x) for x in items]
    return {"status":"PILOT_IMAGES_METADATA_ELIGIBLE" if any(x["eligible_for_pilot"] for x in result)
                   else "BLOCKED_NO_ELIGIBLE_IMAGERY",
            "imagery":result,
            "note":"Eligibility is metadata screening only; image footprint, geotransform and rights must be checked against actual bytes."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--catalog",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    a.output.write_text(json.dumps(gate(json.loads(a.catalog.read_text())),indent=2))
    print(a.output.read_text())
if __name__=="__main__":main()
