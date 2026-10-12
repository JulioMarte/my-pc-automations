"""EXPLORATORY ONLY: construct an explicit assumed cycle for GIS candidates.

Illustrative speed and layover make no claim about travel time or turns.
Using same population cells, produce real geographic coverage + hypothetical
vehicles for 10/15/20 minute schedules, L1 mandatory and optional.
"""
import argparse,csv,json
from pathlib import Path
from optimize_headways import optimize
from prepare_optimization_input import build
import osmnx as ox

ROOT=Path(__file__).resolve().parent
def assumed_cycles(report,average_speed_kmh=18,layover_minutes=12,l1_cycle_minutes=110):
 if average_speed_kmh<=0 or layover_minutes<0:raise ValueError("Invalid illustrative assumptions")
 by_id={x["id"]:x for x in report["competitors"]}
 result={}
 for id,row in by_id.items():
  if id=="L1":
   cycle=l1_cycle_minutes
   rationale="Pre-existing unmeasured L1 planning hypothesis, not computed from distance"
  else:
   if not row["round_trip_km"] or row["round_trip_km"]<=0:raise ValueError("Missing corridor distance "+id)
   cycle=row["round_trip_km"]/average_speed_kmh*60+layover_minutes
   rationale="GIS round-trip length / illustrative mean speed + illustrative terminal layover"
  result[id]={"cycle_minutes":round(cycle,2),"cycle_source":"uncalibrated_simulation",
    "operational_geometry_approved":False,"rationale":rationale,"distance_km":row["round_trip_km"]}
 return result
def main():
 a=argparse.ArgumentParser()
 a.add_argument("--root",type=Path,default=ROOT)
 a.add_argument("--speed-kmh",type=float,default=18)
 a.add_argument("--layover-min",type=float,default=12)
 a.add_argument("--output",type=Path,default=ROOT/"fleet_exploratory_10_20_30.json")
 x=a.parse_args();r=x.root
 comp=json.loads((r/"route_competition.json").read_text())
 config=json.loads((r/"study_config.json").read_text())
 assumed=assumed_cycles(comp,x.speed_kmh,x.layover_min)
 feat=json.loads((r/"discovered_routes.geojson").read_text())["features"]
 pop=json.loads((r/"population.json").read_text())["cells"]
 walk=ox.load_graphml(r/"walk.graphml")
 payload=build(walk,pop,feat,assumed,max_snap=60)
 args={"routes":payload["routes"],"cells":payload["cells"],"budgets":config["fleet_budgets"],
   "headways":config["transit"]["allowed_headways_minutes"],"reserve":config["transit"]["reserve_ratio"],
   "allow_unvalidated":True}
 report={"status":"EXPLORATORY_UNCALIBRATED_NOT_REAL_FLEET",
  "hypotheses":{"speed_kmh":x.speed_kmh,"layover_min":x.layover_min,"l1_cycle_min":110,
    "source":"route geometry plus deliberately hypothetical mean speed, layover; old L1 110 min planning assumption"},
  "input_cells":len(payload["cells"]),"candidate_routes":len(payload["routes"]),
  "with_l1":optimize(**args,l1_required=True),
  "without_l1_constraint":optimize(**args,l1_required=False),
  "warnings":["NO measured cycle times","NO verified bus-turn geometry","Not passenger demand","Frequency 10/15/20 selectable but coverage objective is frequency-insensitive","Use only to find which data matter"]}
 x.output.write_text(json.dumps(report,indent=2,ensure_ascii=False))
 print(json.dumps({"mode":report["status"],"with_l1":report["with_l1"],"without_l1":report["without_l1_constraint"]}))
if __name__=="__main__":main()
