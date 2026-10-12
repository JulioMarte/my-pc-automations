"""Exploratory multi-criterion CP-SAT transit network selector.

Population access, mapped destination access, transfer proximity, a
headway penalty, peak-sized fleet, and route retention across budgets.
Every proxy is explicitly uncalibrated. This is not an OD assignment,
traffic forecast, pedestrian transfer model or vehicle clearance check.
"""
from __future__ import annotations
import math
from ortools.sat.python import cp_model

def distance_m(a,b):
    m=111195
    return m*math.hypot((a[0]-b[0])*math.cos(math.radians((a[1]+b[1])/2)),a[1]-b[1])

def poi_coverage(routes,stopmap,features,meters=450):
    index={}
    for r in routes:
        stops=stopmap.get(r["id"],[])
        if not stops:raise ValueError("No candidate stops for "+r["id"])
        index[r["id"]]=[]
        for i,f in enumerate(features):
            geo=f.get("geometry") or {}
            if geo.get("type")!="Point":continue
            loc=geo.get("coordinates") or []
            if len(loc)<2:continue
            if min(distance_m(loc,s) for s in stops)<=meters:
                index[r["id"]].append(i)
    return index

def transfer_pairs(stopmap,ids,meters=250):
    result=[]
    for i,a in enumerate(ids):
        for b in ids[i+1:]:
            stops_a=stopmap.get(a,[])
            stops_b=stopmap.get(b,[])
            if not stops_a or not stops_b:continue
            best=min(distance_m(x,y) for x in stops_a for y in stops_b)
            if best<=meters:result.append((a,b,round(best,1)))
    return result

def optimize(routes,cells,stopmap,pois,budgets=(10,20,30),headways=(10,15,20),
             reserve=.15,peak_multiplier=1.4,layover_min=12,l1_required=False):
    ids=[r["id"] for r in routes]
    if len(set(ids))!=len(ids):raise ValueError("Duplicate route ID")
    if l1_required and "L1" not in ids:raise ValueError("L1 missing")
    if not 1<=peak_multiplier<=3 or not 0<=reserve<1:raise ValueError("Invalid assumptions")
    poi_by_route=poi_coverage(routes,stopmap,pois)
    pairs=transfer_pairs(stopmap,ids)
    prior=set()
    reports=[]
    for budget in budgets:
        model=cp_model.CpModel()
        choice={(r["id"],h):model.new_bool_var("take_"+r["id"]+"_"+str(h))
                for r in routes for h in headways}
        active={r["id"]:model.new_bool_var("active_"+r["id"]) for r in routes}
        for r in routes:
            id=r["id"]
            model.add(sum(choice[id,h] for h in headways)==active[id])
            if id in prior or (l1_required and id=="L1"):model.add(active[id]==1)
        edges={}
        for a,b,walk in pairs:
            e=model.new_bool_var("transfer_"+a+"_"+b)
            model.add(e<=active[a]);model.add(e<=active[b])
            model.add(e>=active[a]+active[b]-1)
            edges[(a,b)]=e
        single=model.new_bool_var("single_route")
        num=sum(active.values())
        model.add(num==1).only_enforce_if(single)
        model.add(num!=1).only_enforce_if(single.Not())
        for id in ids:
            incident=[e for (a,b),e in edges.items() if id==a or id==b]
            model.add(active[id]<=sum(incident)+single)
        fleet_options={}
        for r in routes:
            minutes=float(r["cycle_minutes"])
            if not minutes>0:raise ValueError("Cycle missing")
            peak_cycle=(max(0,minutes-layover_min)*peak_multiplier)+layover_min
            for h in headways:
                active_buses=math.ceil(peak_cycle/h)
                fleet_options[r["id"],h]=active_buses+math.ceil(active_buses*reserve)
        model.add(sum(fleet_options[id,h]*v for (id,h),v in choice.items())<=budget)
        covered={}
        for cell,value in cells.items():
            v=model.new_bool_var("covered_"+str(cell))
            options=[active[r["id"]] for r in routes if cell in r["covered_cells"]]
            if options:model.add_max_equality(v,options)
            else:model.add(v==0)
            covered[cell]=v
        destination={}
        for idx in range(len(pois)):
            users=[active[id] for id in ids if idx in poi_by_route[id]]
            if not users:continue
            v=model.new_bool_var("poi_"+str(idx))
            model.add_max_equality(v,users)
            destination[idx]=v
        # Named non-demand weights: 1 point per estimated resident;
        # 25 per reachable mapped POI, 100 per prospective transfer,
        # 2 per headway minute for each selected route.
        objective=sum(max(0,round(float(value)))*covered[c] for c,value in cells.items())
        objective+=25*sum(destination.values())
        objective+=100*sum(edges.values())
        objective-=2*sum(h*v for (id,h),v in choice.items())
        model.maximize(objective)
        solver=cp_model.CpSolver()
        solver.parameters.max_time_in_seconds=15
        status=solver.solve(model)
        if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
            reports.append({"budget":budget,"status":"INFEASIBLE_OR_UNSOLVED",
                            "required_existing_routes":sorted(prior),"approved":False})
            continue
        chosen=[{"route":r["id"],"headway_min":h,"fleet_with_reserve":fleet_options[r["id"],h],
                 "peak_cycle_minutes_hypothesis":round((r["cycle_minutes"]-layover_min)*peak_multiplier+layover_min,2)}
                for r in routes for h in headways if solver.value(choice[r["id"],h])]
        selected={x["route"] for x in chosen}
        links=[{"route_a":a,"route_b":b,"straight_line_walk_m":d}
               for a,b,d in pairs if solver.value(edges[a,b])]
        # Connected components of selected transfer graph, not based on straight-line proof of walkability.
        remaining=set(selected);comps=[]
        while remaining:
            root=remaining.pop();part={root};front=[root]
            while front:
                current=front.pop()
                for e in links:
                    if current not in (e["route_a"],e["route_b"]):continue
                    nxt=e["route_b"] if e["route_a"]==current else e["route_a"]
                    if nxt in remaining:remaining.remove(nxt);part.add(nxt);front.append(nxt)
            comps.append(sorted(part))
        reports.append({"budget":budget,"status":"OPTIMAL" if status==cp_model.OPTIMAL else "FEASIBLE_NOT_PROVEN_OPTIMAL",
          "selected":chosen,"transfer_links":links,"transfer_components":comps,
          "transfer_network_connected_proxy":len(comps)<=1,
          "covered_residents_proxy":round(sum(float(v) for k,v in cells.items() if solver.value(covered[k])),2),
          "reachable_poi_count_proxy":sum(solver.value(v) for v in destination.values()),
          "fleet":sum(x["fleet_with_reserve"] for x in chosen),
          "requires_unverified_walk_and_turn_validation":True,"approved":False})
        prior=selected
    return {"status":"EXPLORATORY_MULTIOBJECTIVE_NESTED_CP_SAT",
      "l1_required":l1_required,"peak_multiplier_assumed":peak_multiplier,
      "route_retention_required_between_budgets":True,"budgets":reports,
      "physical_routes_approved":0,
      "objective":"resident proxy + 25 per mapped POI + 100 per transfer edge - 2 per selected route/headway minute",
      "limitations":["Selected routes are retained across increasing budgets, but physical route extension is not designed",
        "Straight-line transfers can hide barriers; full graph connectivity remains a post-solve gate",
        "No OD matrices or time-dependent direction-specific road traffic",
        "Peak multiplier and destination weights are assumptions, not observations",
        "Physical Yutong road clearance and terminal turns remain unverified"]} 
