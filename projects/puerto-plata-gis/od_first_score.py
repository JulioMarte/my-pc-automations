"""Score OD-first one-way candidate fragments with OSM walk-network access.

Every OD and fleet figure is hypothetical; stops are centerline anchors,
not platform recommendations. Return path and turn feasibility are unverified.
"""
import argparse,json,math
from pathlib import Path
import networkx as nx,osmnx as ox
from scipy.spatial import cKDTree
from shapely.geometry import LineString,Point

M=111195.0
def metric(p,ref):
    return ((p[0]-ref[0])*M*math.cos(math.radians(ref[1])),(p[1]-ref[1])*M)

def stop_samples(coords,zone_cells,spacing_m=450):
    origin=coords[0]
    line=LineString([metric(p,origin) for p in coords])
    if line.length<1:return []
    positions=[0.]
    distance=spacing_m
    while distance<line.length-200:
        choices=[(distance,0.)]
        for z in zone_cells:
            x,y=metric(z["center"],origin)
            p=Point(x,y)
            loc=line.project(p)
            gap=p.distance(line)
            if gap<=110 and abs(loc-distance)<=65:
                advantage=float(z["worldpop_residents_estimated"])+15*float(z["poi_weight_proxy"])
                choices.append((loc,advantage/(1+gap)))
        selected=max(choices,key=lambda x:x[1])[0]
        if selected-positions[-1]<350 or selected-positions[-1]>550:selected=distance
        positions.append(selected)
        distance=selected+spacing_m
    if line.length-positions[-1]>1:positions.append(line.length)
    return [[round(origin[0]+line.interpolate(k).x/(M*math.cos(math.radians(origin[1]))),7),
             round(origin[1]+line.interpolate(k).y/M,7)] for k in positions]

def walk_index(graph,cells,max_snap_m=80,cutoff_m=650):
    nodes=list(graph.nodes)
    if not nodes:raise ValueError("Missing walk network")
    scale=math.cos(math.radians(19.78))
    xy=[(float(graph.nodes[n]["x"])*scale,float(graph.nodes[n]["y"])) for n in nodes]
    tree=cKDTree(xy)
    undirected=graph.to_undirected()
    def snap(points):
        if not points:return []
        dist,indices=tree.query([(p[0]*scale,p[1]) for p in points])
        return [(nodes[int(i)],float(d)*M) for i,d in zip(dist,indices)]
    zone_snap=dict(zip([c["id"] for c in cells],snap([c["center"] for c in cells])))
    access={}
    for zone,(node,gap) in zone_snap.items():
        if gap>max_snap_m:continue
        access[zone]=(gap,nx.single_source_dijkstra_path_length(undirected,node,cutoff=cutoff_m,weight="length"))
    return snap,access

def score(candidates,od,zones,walk_graph,config):
    cells=zones["h3_cells"][str(config["primary_resolution"])]
    snap,reach=walk_index(walk_graph,cells)
    exp=next((x for x in od["experiments"] if x["demand_scenario"]=="medium" and x["gravity_exponent"]==1.5),
             od["experiments"][0])
    flows=exp["all_od_flows"]
    params=config.get("service_assumptions",{})
    walk_cap=float(params.get("max_walk_m",500))
    decay=float(params.get("walk_decay_m",350))
    speeds=params.get("speeds_kmh",[12,15,18])
    headways=params.get("headways_min",[10,15,20])
    reserve=float(params.get("fleet_reserve_ratio",.15))
    signal_delay=float(params.get("signals_minutes_per_loop_assumed",5))
    terminal_delay=float(params.get("terminal_recovery_min_assumed",12))
    departures_h=float(params.get("service_hours_per_day_assumed",14))
    capacity=int(params.get("reference_capacity_assumed",95))
    rows=[]
    for candidate in candidates["candidates"]:
        pts=candidate["geometry"]["coordinates"]
        stops=stop_samples(pts,cells)
        snap_stops=snap(stops)
        zone_to_stops={}
        for z,(gap,distances) in reach.items():
            valid=[]
            for i,(node,stub) in enumerate(snap_stops):
                d=gap+stub+distances.get(node,float("inf"))
                if d<=walk_cap:valid.append((i,d))
            if valid:zone_to_stops[z]=valid
        captured=0.;count=0
        for f in flows:
            origin=zone_to_stops.get(f["origin"],[])
            target=zone_to_stops.get(f["destination"],[])
            if not origin or not target:continue
            possible=[(da+db,ia,ib) for ia,da in origin for ib,db in target if ia<ib]
            if not possible:continue
            walking,ia,ib=min(possible)
            # Directional stop order is respected. No unverified return direction scored.
            decay_factor=math.exp(-walking/max(1,decay))
            captured+=f["hypothetical_trips_per_day"]*decay_factor
            count+=1
        hypot=[]
        for speed in speeds:
            # CRITICAL: 2x one-direction road distance is a *placeholder*, not a verified return.
            cycle=2*candidate["distance_m_graph"]/1000/speed*60+max(0,len(stops)-2)*20/60+signal_delay+terminal_delay
            for h in headways:
                buses=math.ceil(cycle/h)
                fleet=buses+math.ceil(buses*reserve)
                day_capacity=capacity*departures_h*60/h
                hypot.append({"speed_kmh_assumed":speed,"headway_min":h,
                    "hypothetical_cycle_min":round(cycle,2),"fleet_proxy":fleet,
                    "hypothetical_od_trips_per_fleet_bus":round(captured/fleet,3),
                    "capture_per_nominal_daily_capacity_proxy":round(captured/day_capacity,4),
                    "capacity_70pct":round(day_capacity*.7,1),"capacity_85pct":round(day_capacity*.85,1),
                    "operational_cycle_valid":False})
        rows.append({"candidate":candidate["id"],"methods":candidate["methods"],
            "stops_centerline_provisional":stops,"stop_count":len(stops),
            "walking_network_access_model":"OSM WALK GRAPH + snap stubs; barriers/curbs unverified",
            "captured_od_trips_hypothetical_base":round(captured,2),
            "matched_od_pairs":count,"scenario":exp["demand_scenario"],
            "gravity_exponent":exp["gravity_exponent"],
            "physical_status":"DUDOSO","operational_gate":"BLOCKED_UNVERIFIED_RETURN_TURNS_CURBS",
            "hypothetical_fleet_cases":hypot})
    rows.sort(key=lambda x:(-max((v["hypothetical_od_trips_per_fleet_bus"] for v in x["hypothetical_fleet_cases"]),default=0),-x["captured_od_trips_hypothetical_base"]))
    return {"status":"OD_FIRST_UNCALIBRATED_SCREENING_NO_VIABLE_BUS_ROUTES",
        "candidate_scores":rows,"ranked_for_review_only":True,
        "initial_route_recommendation":None,"top_6_exploratory":[r["candidate"] for r in rows[:6]],
        "observed_passengers":False,"bus_routes_approved":0,
        "limitations":["Stops lie on graph centerlines, NOT at bus-ready curb locations",
            "Walking network distances include unsurveyed snap connectors and do not certify crossing safety",
            "Scoring counts only OD in the directed route stop order",
            "Return and terminal turn geometry unverified: 2x one-way length is only a cycle assumption",
            "Capture, peak demand, capacity, fleet and daily service window are not measured"]}

def main():
    p=argparse.ArgumentParser()
    for n in ("candidates","od","zones","walk","config","output"):p.add_argument("--"+n,type=Path,required=True)
    a=p.parse_args()
    inputs=[json.loads(getattr(a,n).read_text()) for n in ("candidates","od","zones","config")]
    result=score(inputs[0],inputs[1],inputs[2],ox.load_graphml(a.walk),inputs[3])
    a.output.write_text(json.dumps(result,ensure_ascii=False))
    print(json.dumps({"scored":len(result["candidate_scores"]),
        "best_for_review":result["top_6_exploratory"],"approved":0}))
if __name__=="__main__":main()
