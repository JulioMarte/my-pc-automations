"""Exact maximum-coverage fleet budgets, L1 fixed or optional.

Accepts a GeoJSON point cover assignment table produced by GIS, and cycle-based
vehicle costs. Does not assign rides or infer boardings from synthetic scores.
"""
from __future__ import annotations
import json,math,argparse
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def fleet(cycle,headway=10,reserve=0.15):
 if cycle<=0 or headway<=0 or not(0<=reserve<1):raise ValueError("Bad fleet assumptions")
 active=math.ceil(cycle/headway)
 return active+math.ceil(active*reserve)
def soft_penalty(sinuosity,grade,cfg):
 p=cfg["penalties"]
 return (max(0,sinuosity-p["max_desirable_sinuosity"])*p["sinuosity_excess_weight"]
         +max(0,grade-p["reference_grade_percent"])*p["grade_excess_weight"])
def solve(candidates,cells,budgets=(10,20,30),fixed_l1=False):
 from ortools.sat.python import cp_model
 keys=list(cells)
 for c in candidates:
  if int(c["buses"])<=0:raise ValueError("Unknown/invalid fleet is not admissible")
  if set(c["covered_cells"])-set(cells):raise ValueError("Unknown coverage cell")
 if fixed_l1 and not any(r["id"]=="L1" for r in candidates):raise ValueError("L1 missing")
 results=[]
 for budget in budgets:
  model=cp_model.CpModel()
  take={r["id"]:model.new_bool_var("take_"+r["id"]) for r in candidates}
  cover={k:model.new_bool_var("cover_"+str(k)) for k in keys}
  model.add(sum(int(r["buses"])*take[r["id"]] for r in candidates)<=budget)
  for k in keys:
   has=[take[r["id"]] for r in candidates if k in r["covered_cells"]]
   if has:model.add_max_equality(cover[k],has)
   else:model.add(cover[k]==0)
  if fixed_l1:model.add(take["L1"]==1)
  # WorldPop weights discretized to estimated hundredths for CP-SAT.
  model.maximize(sum(max(0,round(float(cells[k])*100))*cover[k] for k in keys))
  solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=15
  status=solver.solve(model)
  if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
   results.append({"fleet_budget":budget,"status":"INFEASIBLE_OR_UNSOLVED","l1_required":fixed_l1});continue
  selected=[r for r in candidates if solver.value(take[r["id"]])]
  results.append({"fleet_budget":budget,"status":"OPTIMAL" if status==cp_model.OPTIMAL else "FEASIBLE_NOT_PROVEN_OPTIMAL",
    "l1_required":fixed_l1,"selected":[x["id"] for x in selected],
    "buses":sum(int(x["buses"]) for x in selected),
    "estimated_residents_with_stop_access":round(sum(float(cells[k]) for k in keys if solver.value(cover[k])),2),
    "note":"Coverage-only proxy; passenger demand, transfers and turns not evaluated"})
 return results
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--input",type=Path,required=True,help="JSON {cells:{id: population}, routes:[{id,buses,covered_cells}]}")
 p.add_argument("--config",type=Path,default=ROOT/"study_config.json")
 p.add_argument("--output",type=Path,default=ROOT/"fleet_optimization.json")
 a=p.parse_args();inp=json.loads(a.input.read_text());cfg=json.loads(a.config.read_text())
 report={"data_source":str(a.input),"method":"OR-Tools CP-SAT maximum weighted coverage under fleet budget",
 "assumptions":["Only valid if coverage cells are precomputed with the same GIS graph and geometry rules",
   "Bus costs must originate from route-specific measured/simulated cycles and reserve rates",
   "No predicted boardings, routing feasibility, fare or transfer times"],
 "with_l1":solve(inp["routes"],inp["cells"],cfg["fleet_budgets"],True),
 "without_l1_constraint":solve(inp["routes"],inp["cells"],cfg["fleet_budgets"],False)}
 a.output.write_text(json.dumps(report,indent=2,ensure_ascii=False))
 print("Budgets",cfg["fleet_budgets"])
if __name__=="__main__":main()
