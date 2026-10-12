"""Headway-choice fleet optimization. Every route may choose OFF, 10, 15 or 20 min.

NO operational approval without verified cycles, route geometry and cell-level
accessibility. Synthetic scoring input can only produce explicitly hypothetical
solutions. A route's coverage is counted once regardless of selected headway.
"""
import argparse,json,math
from pathlib import Path
from ortools.sat.python import cp_model

ROOT=Path(__file__).resolve().parent

def vehicle_requirement(cycle_minutes,headway_minutes,reserve_ratio):
 if cycle_minutes is None or cycle_minutes <= 0:raise ValueError("A positive route-specific cycle is required")
 if headway_minutes not in (10,15,20):raise ValueError("Unsupported headway")
 if not 0<=reserve_ratio<1:raise ValueError("Reserve ratio must be [0,1)")
 active=math.ceil(cycle_minutes/headway_minutes)
 return {"active":active,"reserve":math.ceil(active*reserve_ratio),"total":active+math.ceil(active*reserve_ratio)}

def validate_route(route):
 required=("id","covered_cells","cycle_minutes","cycle_source","operational_geometry_approved")
 if any(k not in route for k in required):raise ValueError(f"Missing route data: {route.get('id','?')}")
 if route["cycle_source"] not in ("measured","calibrated_simulation","uncalibrated_simulation"):
  raise ValueError(f"Unknown source for {route['id']}")
 if route["cycle_minutes"] is None or route["cycle_minutes"]<=0:raise ValueError("Unknown cycle is forbidden")
 if route["operational_geometry_approved"] not in (True,False):raise ValueError("Geometry approval must be explicit")

def optimize(routes,cells,budgets=(10,20,30),headways=(10,15,20),reserve=0.15,l1_required=False,allow_unvalidated=False):
 if len({r["id"] for r in routes})!=len(routes):raise ValueError("Duplicate route IDs")
 for route in routes:
  validate_route(route)
  if not allow_unvalidated and (not route["operational_geometry_approved"] or route["cycle_source"]=="uncalibrated_simulation"):
   raise ValueError(f"Route {route['id']} not validated; supply --exploratory to run hypothetical comparison")
  if set(route["covered_cells"])-set(cells):raise ValueError("Coverage references unknown cells")
 if l1_required and not any(r["id"]=="L1" for r in routes):raise ValueError("L1 mandatory but missing")
 reports=[]
 for budget in budgets:
  model=cp_model.CpModel()
  selections={(r["id"],h):model.new_bool_var(f"choose_{r['id']}_{h}") for r in routes for h in headways}
  for r in routes:model.add(sum(selections[r["id"],h] for h in headways)<=1)
  for r in routes:
   if l1_required and r["id"]=="L1":model.add(sum(selections[r["id"],h] for h in headways)==1)
  model.add(sum(vehicle_requirement(r["cycle_minutes"],h,reserve)["total"]*selections[r["id"],h] for r in routes for h in headways)<=budget)
  visited={k:model.new_bool_var("covered_"+str(k)) for k in cells}
  for k in cells:
   opts=[selections[r["id"],h] for r in routes if k in r["covered_cells"] for h in headways]
   if opts:model.add_max_equality(visited[k],opts)
   else:model.add(visited[k]==0)
  model.maximize(sum(max(0,round(float(weight)*100))*visited[k] for k,weight in cells.items()))
  solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=20
  status=solver.solve(model)
  if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
   reports.append({"budget":budget,"status":"INFEASIBLE_OR_UNSOLVED","l1_required":l1_required});continue
  picked=[{"route":r["id"],"headway_min":h,"cycle_min":r["cycle_minutes"],
     "cycle_source":r["cycle_source"],"fleet":vehicle_requirement(r["cycle_minutes"],h,reserve)}
     for r in routes for h in headways if solver.value(selections[r["id"],h])]
  reports.append({"budget":budget,"l1_required":l1_required,
    "status":"OPTIMAL" if status==cp_model.OPTIMAL else "FEASIBLE_NOT_PROVEN_OPTIMAL",
    "selected":picked,"buses":sum(x["fleet"]["total"] for x in picked),
    "covered_residents_estimate":round(sum(float(v) for k,v in cells.items() if solver.value(visited[k])),2),
    "validation_level":"EXPLORATORY_ONLY" if allow_unvalidated else "INPUTS_CLAIM_VALIDATED",
    "caveat":"Maximum stop access, not number of direct journeys or passengers"})
 return reports

def main():
 a=argparse.ArgumentParser()
 a.add_argument("--input",type=Path,required=True)
 a.add_argument("--config",type=Path,default=ROOT/"study_config.json")
 a.add_argument("--output",type=Path,default=ROOT/"headway_fleet_scenarios.json")
 a.add_argument("--exploratory",action="store_true")
 args=a.parse_args()
 inp=json.loads(args.input.read_text());cfg=json.loads(args.config.read_text())
 params={"routes":inp["routes"],"cells":inp["cells"],"budgets":cfg["fleet_budgets"],
         "headways":cfg["transit"]["allowed_headways_minutes"],"reserve":cfg["transit"]["reserve_ratio"],
         "allow_unvalidated":args.exploratory}
 r={"scenario_mode":"EXPLORATORY" if args.exploratory else "VALIDATED_INPUTS_ONLY",
   "with_l1":optimize(**params,l1_required=True),
   "without_l1_constraint":optimize(**params,l1_required=False),
   "warning":"The optimum applies only to weighted stop coverage; GTFS/r5py and observed OD are required before network approval"}
 args.output.write_text(json.dumps(r,ensure_ascii=False,indent=2))
 print(json.dumps({"mode":r["scenario_mode"],"with_l1":r["with_l1"],"without_l1_constraint":r["without_l1_constraint"]},ensure_ascii=False))
if __name__=="__main__":main()
