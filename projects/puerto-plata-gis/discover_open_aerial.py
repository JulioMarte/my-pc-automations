"""Discover imagery over Puerto Plata via HOT OpenAerialMap STAC metadata.

Discovery is NOT downloading imagery and does NOT establish mapping rights.
The catalog is expected to change; errors become recorded evidence.
"""
import argparse,datetime,json,urllib.request,urllib.error
from pathlib import Path

STAC_URL="https://api.imagery.hotosm.org/stac/search"
PUERTO_PLATA_BBOX=[-70.752,19.740,-70.620,19.836]

def parse_stac(payload):
    items=[]
    if not isinstance(payload,dict) or not isinstance(payload.get("features"),list):
        raise ValueError("Unexpected STAC response format")
    for feature in payload["features"]:
        props=feature.get("properties") or {}
        assets=feature.get("assets") or {}
        items.append({
            "id":feature.get("id"),"bbox":feature.get("bbox"),
            "datetime":props.get("datetime") or props.get("start_datetime"),
            "gsd_m_reported":props.get("gsd"),
            "license_reported":props.get("license"),
            "providers":props.get("providers"),
            "asset_types":sorted(assets),
            "rights_for_measurement_confirmed":False,
            "horizontal_accuracy_confirmed":False,
            "verified_puerto_plata_coverage":False,
            "eligible_for_measurement":False,
        })
    return items

def retrieve(timeout=45):
    query={"bbox":PUERTO_PLATA_BBOX,"collections":["openaerialmap"],"limit":100}
    request=urllib.request.Request(
        STAC_URL,
        data=json.dumps(query).encode("utf-8"),
        method="POST",
        headers={"Content-Type":"application/json","Accept":"application/geo+json",
                 "User-Agent":"PuertoPlataGIS-ImageryDiscovery/1.0"})
    record={"queried_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source":STAC_URL,"query":query,"images":[],"status":"BLOCKED_DISCOVERY_ERROR",
            "notes":"No map rights or width measurements inferred from this catalog"}
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            record["http_status"]=response.status
            body=response.read(6_000_000)
        payload=json.loads(body)
        record["images"]=parse_stac(payload)
        record["found_on_page"]=len(record["images"])
        record["status"]="DISCOVERED_UNVERIFIED_IMAGES" if record["images"] else "NO_IMAGERY_IN_CATALOG_FOR_BBOX"
    except (OSError,TimeoutError,ValueError,json.JSONDecodeError) as exc:
        record["failure"]=str(exc)[:500]
    return record

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--timeout",type=int,default=45)
    p.add_argument("--strict",action="store_true")
    a=p.parse_args()
    report=retrieve(a.timeout)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(json.dumps({"status":report["status"],"found":len(report["images"]),
                      "failure":report.get("failure")},ensure_ascii=False))
    if a.strict and report["status"]=="BLOCKED_DISCOVERY_ERROR":
        raise SystemExit(2)
if __name__=="__main__":main()
