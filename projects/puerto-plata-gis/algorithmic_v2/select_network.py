"""Select unique synthetic OD by CP-SAT; both independent and nested phases.

All paths/turns remain physically unverified. This is not an operational
recommendation and does not count a synthetic OD twice on overlapping lines.
"""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
from ortools.sat.python import cp_model

def optimize(rows,flows,budgets=(10,20,30),headways=(10,15,20),reserve=.15,
             progressive=False,seconds=10,maximum_routes=65,maximum_od=150,od_scenario_key="medium_beta_1"):
    routes=sorted(rows,key=lambda x:-x["baseline_relative_od_accessible_proxy"])[:maximum_routes]
    flow_rows=sorted(flows,key=lambda x:-x["relative_flow_units"])[:maximum_od]
    ids=[r["candidate_id"] for r in routes]
    if len(set(ids))!=len(ids):raise ValueError("Duplicate candidate IDs")
    # Only relative model units; multiplier 1000 retains small OD contributions.
    weights={}
    for r in routes:
        weights[r["candidate_id"]]={k:max(0,round(v*1000)) for k,v in r["captured_od_contributions_by_scenario"].get(od_scenario_key,{}).items()}
    prior=set();reports=[]
    for budget in budgets:
        model=cp_model.CpModel()
        select={(id,h):model.new_bool_var("use_"+id+"_"+str(h)) for id in ids for h in headways}
        selected={id:model.new_bool_var("selected_"+id) for id in ids}
        fleet_cost={}
        for r in routes:
            id=r["candidate_id"]
            model.add(sum(select[id,h] for h in headways)==selected[id])
            for h in headways:
                service=next((s for s in r["service_scenarios"] if s["headway_minutes"]==h
                   and s["speed_kmh_assumed"]==15 and abs(s["reserve_ratio_assumed"]-reserve)<1e-8),None)
                if service is None:raise ValueError("Missing service cost scenario")
                fleet_cost[id,h]=service["fleet_buses_proxy"]
            if progressive and id in prior:model.add(selected[id]==1)
        model.add(sum(fleet_cost[id,h]*v for (id,h),v in select.items())<=budget)
        # Unique OD objective: best captured contribution among chosen routes, not SUM.
        od_terms=[]
        for index,od in enumerate(flow_rows):
            od_id=od["origin"]+"|"+od["destination"]
            opts=[weights[id].get(od_id,0)*selected[id] for id in ids if weights[id].get(od_id,0)>0]
            if not opts:continue
            upper=max(weights[id].get(od_id,0) for id in ids)
            y=model.new_int_var(0,upper,"best_od_"+str(index))
            model.add_max_equality(y,opts)
            od_terms.append(y)
        # Smaller headway penalty, OD max keeps overlap from double counting.
        model.maximize(sum(od_terms)-sum(h*select[id,h] for id,h in select))
        solver=cp_model.CpSolver()
        solver.parameters.max_time_in_seconds=seconds
        status=solver.solve(model)
        if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
            outcome="UNSOLVED_TIME_LIMIT_OR_UNKNOWN" if status==cp_model.UNKNOWN else "INFEASIBLE" if status==cp_model.INFEASIBLE else "MODEL_INVALID"
            reports.append({"budget":budget,"status":outcome,"selected_routes":[],"approved":False})
            if progressive:break
            continue
        chosen=[{"candidate_id":id,"headway_minutes":h,"fleet_buses_proxy":fleet_cost[id,h]}
                for id in ids for h in headways if solver.value(select[id,h])]
        now={x["candidate_id"] for x in chosen}
        unique=int(sum(solver.value(z) for z in od_terms))
        reports.append({"budget":budget,
            "status":"OPTIMAL" if status==cp_model.OPTIMAL else "FEASIBLE_NOT_PROVEN_OPTIMAL",
            "selected_routes":chosen,
            "total_fleet_buses":sum(x["fleet_buses_proxy"] for x in chosen),
            "unique_od_capture_score_relative":round(unique/1000,3),
            "previous_routes_retained":sorted(prior&now),
            "new_routes":sorted(now-prior),"removed_prior_routes":sorted(prior-now),
            "transfer_walk_access_verified":False,"physically_approved":False})
        if progressive:prior=now
    return {"status":"UNIQUE_SYNTHETIC_OD_CP_SAT_EXPLORATORY",
        "progressive":progressive,"candidate_pool_size":len(routes),
        "od_pairs_optimised":len(flow_rows),"budget_results":reports,
        "operationally_approved":0,
        "limitations":["Uses synthetic OD and per-route maximum contribution, not observed ridership",
            "Two-leg transfers and path-dependent OD journeys not yet added to objective",
            "Only top candidate/OD subset optimized, not full 300 candidate global optimum",
            "Peak travel times, true bus terminal turning and traffic remain uncalibrated",
            "Service cycles double outbound distance for hypothetical return, not verified loops",
            "No physical bus clearance verified"]}

def build(scored,od):
    outputs=[]
    for name in ("low","medium","high"):
        scenario=next(s for s in od["scenarios"] if s["level"]==name and s["exponent"]==1)
        a=optimize(scored["ranked_candidates"],scenario["od"],progressive=False,od_scenario_key=f"{name}_beta_1")
        b=optimize(scored["ranked_candidates"],scenario["od"],progressive=True,od_scenario_key=f"{name}_beta_1")
        outputs.append({"demand_scenario":name,"independent":a,"progressive":b})
    return {"status":"ALGORITHMIC_NETWORKS_EXPLORATORY",
        "scenarios":outputs,"physical_bus_routes_approved":0,
        "limitation":"Per-scenario OD incidence recalculated from walking-access model; beta sensitivity and calibrated transfer OD remain outside this selection."}

def main():
    p=argparse.ArgumentParser()
    for key in ("scored","od","output"):p.add_argument("--"+key,type=Path,required=True)
    a=p.parse_args()
    r=build(json.loads(a.scored.read_text()),json.loads(a.od.read_text()))
    a.output.write_text(json.dumps(r,separators=(",",":")))
    print(json.dumps({"scenario_count":len(r["scenarios"]),
        "solved":[(x["demand_scenario"],[b["status"] for b in x["independent"]["budget_results"]],
                   [b["status"] for b in x["progressive"]["budget_results"]]) for x in r["scenarios"]]}))
if __name__=="__main__":main()
