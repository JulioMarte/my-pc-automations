"""Planificador de operación y conexiones de transporte de Puerto Plata.

Hipótesis explícitas, NO datos de demanda observada ni rutas validadas.
Solo estándar Python. Ejecutar: python transit_planner.py --output network_scenarios.json
"""
import argparse, json, math
from pathlib import Path

DEFAULT={
 "service_hours":14,
 "operating_days_month":26,
 "reserve_large":2,"reserve_small":2,
 "vehicle_cost_dop":{"large":8800000,"small":4000000},
 "routes":[
  {"id":"L1","name":"UASD–Oasis","type":"large","capacity":60,"cycle_minutes":110,
   "peak_headway":10,"offpeak_headway":15,"boardings_per_day_assumption":2000},
  {"id":"L2","name":"San Marcos–Padre Granero","type":"small","capacity":30,"cycle_minutes":90,
   "peak_headway":15,"offpeak_headway":20,"boardings_per_day_assumption":900}],
 "periods":[
  {"name":"madrugada","from":"05:30","to":"06:30","peak":False},
  {"name":"manana","from":"06:30","to":"09:00","peak":True},
  {"name":"mediodia_1","from":"09:00","to":"12:00","peak":False},
  {"name":"almuerzo","from":"12:00","to":"14:00","peak":True},
  {"name":"tarde","from":"14:00","to":"16:30","peak":False},
  {"name":"regreso","from":"16:30","to":"19:30","peak":True}],
 "transfers":[{"from":"L2","to":"L1","walk_minutes":2,"timed_connection_target_minutes":4,
   "fare_window_minutes":60,"fare_dop":40}],
 "objective_weights":{"walk":1,"wait":1.7,"ride":1,"transfer_penalty_minutes":6},
 "boarding_distribution_assumption":{"madrugada":0.05,"manana":0.25,"mediodia_1":0.14,"almuerzo":0.14,"tarde":0.16,"regreso":0.26}
}
def minutes(t):
 h,m=map(int,t.split(":"));return 60*h+m
def ceil_div(a,b):return math.ceil(a/b)
def validate(d):
 ids=[r["id"] for r in d["routes"]]
 if len(ids)!=len(set(ids)):raise ValueError("IDs duplicados")
 for p in d["periods"]:
  if minutes(p["to"])<=minutes(p["from"]):raise ValueError("Periodo no válido")
 for r in d["routes"]:
  if min(r["capacity"],r["cycle_minutes"],r["peak_headway"],r["offpeak_headway"])<=0:raise ValueError("Valores inválidos")
 for t in d["transfers"]:
  if t["from"] not in ids or t["to"] not in ids:raise ValueError("Transferencia sin ruta")
def evaluate(d):
 validate(d);periods=[];max_by_route={}
 for p in d["periods"]:
  duration=minutes(p["to"])-minutes(p["from"])
  rows=[];total=0
  for r in d["routes"]:
   h=r["peak_headway"] if p["peak"] else r["offpeak_headway"]
   active=ceil_div(r["cycle_minutes"],h);total+=active
   max_by_route[r["id"]]=max(max_by_route.get(r["id"],0),active)
   departures=duration/h
   rows.append({"id":r["id"],"headway_minutes":h,"active_vehicles":active,
     "departures_per_direction_theoretical":round(departures,2),
     "places_per_hour_per_direction":round(r["capacity"]*60/h,1),
     "expected_random_wait_minutes":h/2})
  periods.append({"period":p["name"],"duration_minutes":duration,"peak":p["peak"],"active_total":total,"lines":rows})
 costs=d["vehicle_cost_dop"]
 fleet=[{"id":r["id"],"vehicle_type":r["type"],"active":max_by_route[r["id"]],
  "capacity":r["capacity"],"cost_per_vehicle_dop":costs[r["type"]]} for r in d["routes"]]
 needed_by_type={t:sum(x["active"] for x in fleet if x["vehicle_type"]==t) for t in ("large","small")}
 fleet_cost=sum(x["active"]*x["cost_per_vehicle_dop"] for x in fleet)
 fleet_cost+=d["reserve_large"]*costs["large"]+d["reserve_small"]*costs["small"]
 transfers=[]
 for tr in d["transfers"]:
  origin=next(x for x in d["routes"] if x["id"]==tr["from"])
  target=next(x for x in d["routes"] if x["id"]==tr["to"])
  checks=[]
  for p in d["periods"]:
   target_h=target["peak_headway"] if p["peak"] else target["offpeak_headway"]
   walk=tr["walk_minutes"]
   # Not a timetable optimization: these are a lower bound and headway-derived expectations.
   checks.append({"period":p["name"],"uncoordinated_mean_wait_minutes":target_h/2,
    "best_case_usable_transfer_minutes":walk,
    "target_total_transfer_minutes":walk+tr["timed_connection_target_minutes"],
    "coordination_unverified":True})
  transfers.append({"from":tr["from"],"to":tr["to"],"fare_window_minutes":tr["fare_window_minutes"],
    "walk_minutes":tr["walk_minutes"],"periods":checks})
 return {"method":"fixed-headway service planner, not demand-calibrated network optimization",
  "uncertainties":["Route cycles assumed, not GPS measured","Boarding demand unobserved","Peak periods hypothetical",
    "Turn restrictions, stops and safe transfers not validated","Actual departures require terminal timetable and vehicle blocking"],
  "periods":periods,"fleet":{"active_peak_by_route":fleet,"reserves":{"large":d["reserve_large"],"small":d["reserve_small"]},
   "fleet_total":sum(needed_by_type.values())+d["reserve_large"]+d["reserve_small"],
   "capital_dop_assumption":fleet_cost},
  "transfers":transfers}
def main():
 p=argparse.ArgumentParser();p.add_argument("--config");p.add_argument("--output",default="network_scenarios.json")
 a=p.parse_args();d=json.loads(Path(a.config).read_text()) if a.config else DEFAULT
 result=evaluate(d);Path(a.output).write_text(json.dumps({"configuration":d,"results":result},ensure_ascii=False,indent=2))
 print(f"Fleet {result['fleet']['fleet_total']} vehicles; assumed capital DOP {result['fleet']['capital_dop_assumption']:,}")
if __name__=="__main__":main()
