"""Exploratory service-cycle reconstruction for selected Puerto Plata routes.

Connect final waypoint to initial waypoint on bus-costing OSM graph where
separated. Include explicit dwell, recovery and speed hypotheses. NEVER
certify turning movements or infer headways from an incomplete connector.
"""
import json,math
from valhalla_waypoint_route import distance_m
from valhalla_route_shape import extract_shape

SPEEDS=(12,18,24)
DWELL_S=(15,30)
RECOVERY_MIN=(8,12)

def compute(waypoint_report,actor,speeds=SPEEDS,dwell_seconds=DWELL_S,recovery_minutes=RECOVERY_MIN):
    rows=[]
    for route in waypoint_report.get("routes",[]):
        ends=route.get("endpoints") or {}
        a,b=ends.get("start"),ends.get("end")
        connector={"status":"NOT_EVALUATED","distance_km":None,"time_seconds":None,
                   "vehicle_turnaround_verified":False}
        if not route.get("complete_routable_sequence") or not a or not b:
            connector["status"]="BLOCKED_INCOMPLETE_ROUTE"
        elif distance_m(a,b)<2:
            connector.update(status="ENDPOINTS_COINCIDENT_TO_WITHIN_2M",distance_km=0.0,time_seconds=0.0)
        else:
            req={"locations":[{"lat":b[1],"lon":b[0]},{"lat":a[1],"lon":a[0]}],
                 "costing":"bus","directions_options":{"units":"kilometers"}}
            try:
                response=actor.route(req)
                if isinstance(response,str):response=json.loads(response)
                summary=response["trip"]["summary"]
                shape=extract_shape(response)
                length=float(summary["length"])
                time=float(summary["time"])
                if not (0.02<length<200 and 0<time<100000 and shape["status"]=="ROAD_GRAPH_SHAPE_NOT_SWEPT_PATH"):
                    raise ValueError("Invalid connector path or missing shape")
                connector.update(status="ROUTED_GRAPH_CONNECTOR",distance_km=length,
                                 time_seconds=time,shape=shape["geometry"])
            except Exception as e:
                connector.update(status="BLOCKED_GRAPH_CONNECTOR",error=str(e)[:230])
        usable=(route.get("complete_routable_sequence") and connector["distance_km"] is not None
                and route.get("sum_segment_distance_km") is not None)
        scenarios=[]
        if usable:
            km=route["sum_segment_distance_km"]+connector["distance_km"]
            for speed in speeds:
                for dwell in dwell_seconds:
                    for recovery in recovery_minutes:
                        if speed<=0 or dwell<0 or recovery<0:raise ValueError("Invalid hypothetical parameter")
                        visit_count=max(route["waypoints"]-1,0)
                        mins=60*km/speed + visit_count*dwell/60 + recovery
                        scenarios.append({"speed_kmh_assumed":speed,"dwell_s_per_waypoint_assumed":dwell,
                            "recovery_min_assumed":recovery,"cycle_minutes_exploratory":round(mins,2),
                            "service_distance_km":round(km,3),"cycle_approved":False})
        rows.append({"candidate":route["id"],"waypoint_leg_km":route.get("sum_segment_distance_km"),
            "connector":connector,"fully_routable_graph_loop":bool(usable),
            "scenarios":scenarios,"terminal_turnaround_approved":False,
            "measured_runtime_available":False})
    return {"status":"HYPOTHETICAL_FULL_GRAPH_LOOP_NOT_OPERATIONALLY_APPROVED",
        "routes":rows,"routable_loops":sum(r["fully_routable_graph_loop"] for r in rows),
        "approved_service_cycles":0,
        "limitations":["Connector may duplicate some roadway and does not prove a legal bus U-turn",
            "Stop dwell counted at provisional waypoint transitions, not measured boarding demand",
            "Speed and recovery times are scenarios only; no traffic calibration",
            "No geometry or terminal maneuver certified for the 12.17m bus"]}
