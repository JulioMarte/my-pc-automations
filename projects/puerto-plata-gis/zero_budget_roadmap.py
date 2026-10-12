"""Evidence-based no-budget priorities for Puerto Plata transit GIS.

The plan is deliberately independent of drone flights, municipality surveys
and commercial imagery. Nonexistent observations remain blockers, not passes.
"""
import argparse,json
from pathlib import Path

def assess(road,image,turn):
    required=("roads","measurements_count")
    if any(k not in road for k in required):
        raise ValueError("Missing OSM inventory evidence")
    if "turns" not in image or "assessed_turns" not in image:
        raise ValueError("Missing nine-turn imagery evidence")
    if "risks" not in turn or "total_tasks" not in turn:
        raise ValueError("Missing turn queue evidence")
    if image["assessed_turns"] != turn["total_tasks"]:
        raise ValueError("Inconsistent turn counts")
    if road["measurements_count"] < 0:
        raise ValueError("Negative width observation count")
    n=road["roads"]["road_features"]
    if n<=0:raise ValueError("No road graph inventory")
    tags=road["roads"]["tag_counts"]
    width_tags=tags.get("width",0)
    available=min(width_tags,n)
    tasks=[
      {"id":"OSM_ATTRIBUTE_COVERAGE","priority":1,"state":"READY_FOR_DESK_ANALYSIS",
       "evidence":{"directed_edges":n,"tagged_width_edges":width_tags,
                   "width_tag_fraction":round(available/n,5),"lanes_tagged":tags.get("lanes",0)},
       "work":"Consolidate OSM lane/width/oneway/parking/surface restrictions and unknown coverage."},
      {"id":"REAL_ROUTED_PATH_GEOMETRY","priority":2,"state":"REQUIRES_IMPLEMENTATION",
       "work":"Persist actual Valhalla directed polyline and edge IDs for each outbound/inbound route, not synthetic MultiPoint lines."},
      {"id":"TOPOLOGY_AND_TRANSFER_QA","priority":3,"state":"REQUIRES_IMPLEMENTATION",
       "work":"Audit one-way streets, forbidden turns, detours, accessibility and stop-transfer network connectivity."},
      {"id":"FLEET_SENSITIVITY_AND_SERVICE","priority":4,"state":"EXPLORATORY_ONLY",
       "work":"Evaluate headways/cycles with Valhalla path distances and uncertainty scenarios; no invented demand."},
      {"id":"DEMAND_SENSITIVITY","priority":5,"state":"EXPLORATORY_ONLY",
       "work":"Vary population proxy, stop catchments, OD assumptions; identify robust routes versus unstable rankings."},
      {"id":"OPEN_IMAGERY_METADATA","priority":6,
       "state":"REFERENCE_ONLY" if image["fit_for_precision_measurements"]==0 else "PILOT_CANDIDATE_UNVERIFIED",
       "evidence":{"screened_waypoints":image["assessed_turns"],
                   "bbox_overlaps":image["turns_with_catalog_bbox_overlap"],
                   "qualified_for_precision":image["fit_for_precision_measurements"]},
       "work":"Retain STAC as visual metadata, revisit only if new freely usable images appear."},
      {"id":"PHYSICAL_CLEARANCE","priority":7,"state":"DEFERRED_NO_MEASUREMENT_BUDGET",
       "evidence":{"measured_cross_sections":road["measurements_count"],
                   "approved_turns":turn["maneuvers_approved"]},
       "work":"Do not simulate final curb clearance without measured curbs and a validated swept-path template."}
    ]
    if turn["maneuvers_approved"]!=0 or any(t.get("physical_turn_status")!="NOT_ASSESSED" for t in turn["risks"]):
        raise ValueError("Input claims bus approval; check audit gate first")
    return {"status":"ZERO_BUDGET_WORKPLAN_NOT_ENGINEERING_APPROVAL","vehicle":"Yutong ZK6126HG",
        "no_fieldwork":True,"no_paid_imagery":True,"operationally_approved_routes":0,
        "tasks":tasks,"priority_order":[t["id"] for t in tasks],
        "next_milestone":"REAL_ROUTED_PATH_GEOMETRY",
        "note":"Ready means evidence for desk analysis only; no physical bus clearance certified."}

def main():
    p=argparse.ArgumentParser()
    for name in ("road","image","turn","output"):
        p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args()
    result=assess(json.loads(a.road.read_text()),json.loads(a.image.read_text()),
                  json.loads(a.turn.read_text()))
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({"status":result["status"],"tasks":len(result["tasks"]),
                      "next":result["next_milestone"]}))
if __name__=="__main__":main()
