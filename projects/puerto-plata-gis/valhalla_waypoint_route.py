"""Route consecutively via actual provisional candidate waypoints on local Valhalla.

Waypoints are NOT certified stops; routing between them does not imply curb,
terminal maneuver or bus swept-path clearance. Intended only for a 3-route
exploratory comparison, not for automatically approving a service network.
"""
import math
from valhalla_route_shape import extract_shape

TARGET=("C00-09","C00-10","C02-04")

def distance_m(a,b):
    scale=111195.0
    return math.hypot((a[0]-b[0])*scale*math.cos(math.radians((a[1]+b[1])/2)),
                      (a[1]-b[1])*scale)

def route_waypoints(features,actor,targets=TARGET):
    found={f.get("properties",{}).get("id"):f for f in features}
    if any(r not in found for r in targets):
        raise ValueError("Missing required provisional routes")
    routes=[]
    for rid in targets:
        feature=found[rid]
        if feature.get("geometry",{}).get("type")!="MultiPoint":
            raise ValueError("Candidate lacks ordered waypoints")
        coords=feature["geometry"]["coordinates"]
        if len(coords)<3:raise ValueError("Too few candidate waypoints")
        segments=[]
        joined=[]
        failures=0
        total_km=0.0
        total_seconds=0.0
        for i,(a,b) in enumerate(zip(coords,coords[1:])):
            if distance_m(a,b)<2:
                segments.append({"from_index":i,"to_index":i+1,"status":"DUPLICATE_WAYPOINT_SKIPPED"})
                continue
            request={"locations":[{"lat":a[1],"lon":a[0]},{"lat":b[1],"lon":b[0]}],
                     "costing":"bus","directions_options":{"units":"kilometers"}}
            try:
                raw=actor.route(request)
                if isinstance(raw,str):
                    import json
                    raw=json.loads(raw)
                trip=raw["trip"]; summary=trip["summary"]
                km=float(summary["length"])
                seconds=float(summary["time"])
                shape=extract_shape(raw)
                if not (0.02<km<200 and 0<seconds<100000) or shape["status"]!="ROAD_GRAPH_SHAPE_NOT_SWEPT_PATH":
                    raise ValueError("Missing usable routed shape or implausible segment")
                pts=shape["geometry"]["coordinates"]
                if joined and joined[-1]==pts[0]:pts=pts[1:]
                joined.extend(pts)
                total_km+=km
                total_seconds+=seconds
                segments.append({"from_index":i,"to_index":i+1,"status":"ROUTED",
                                 "distance_km":km,"time_seconds":seconds,
                                 "shape_vertices":shape["vertex_count"]})
            except Exception as e:
                failures+=1
                segments.append({"from_index":i,"to_index":i+1,"status":"BLOCKED",
                                 "reason":str(e)[:230]})
        success=failures==0 and len(joined)>=2
        closure_m=round(distance_m(coords[0],coords[-1]),1)
        closed_sequence=closure_m<=30
        endpoints={"start":coords[0],"end":coords[-1],"distance_between_ends_m":closure_m,"closed_within_30m":closed_sequence}
        routes.append({"id":rid,"waypoints":len(coords),"segments":segments,
                       "failed_segments":failures,"complete_routable_sequence":success,
                       "endpoints":endpoints,"validated_service_cycle":False,
                       "route_distance_is_round_trip":False,
                       "sum_segment_distance_km":round(total_km,3) if success else None,
                       "sum_segment_time_s":round(total_seconds,1) if success else None,
                       "physical_bus_geometry_approved":False,
                       "shape":{"type":"LineString","coordinates":joined} if success else None})
    return {"status":"WAYPOINT_CONSTRAINED_EXPLORATORY_ROUTING",
            "vehicle":"Yutong ZK6126HG","routes":routes,
            "complete_routes":sum(x["complete_routable_sequence"] for x in routes),
            "physical_routes_approved":0,
            "limitations":["Stops are point samples, not surveyed curb-safe stop positions",
                "All legs are Valhalla bus graph paths, not one continuous approved bus operation",
                "Terminal turnaround and legal stop access remain unverified",
                "Ordered waypoint distance is NOT a validated round-trip cycle even when endpoints coincide"]}

def to_geojson(report):
    return {"type":"FeatureCollection","features":[
        {"type":"Feature","properties":{"id":r["id"],
             "route_type":"ordered_waypoint_constrained","physical_approval":False,
             "distance_km":r["sum_segment_distance_km"]},
         "geometry":r["shape"]}
        for r in report["routes"] if r["complete_routable_sequence"]]}
