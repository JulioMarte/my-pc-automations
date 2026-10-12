"""Score algorithmically generated routes using WALK network distance.

All OD flows are relative synthetic, not observed trips. Candidate service
cycles assume a hypothetical return; no route is eligible for commissioning.
"""
import argparse,json,math,bisect
from pathlib import Path
import networkx as nx
import osmnx as ox
from scipy.spatial import cKDTree
from pyproj import Transformer

def stop_points(coords,spacing_m=450,hotspots=None,snap_search_m=25):
    if not 350<=spacing_m<=600:raise ValueError("Unreasonable stop spacing")
    project=Transformer.from_crs(4326,32619,always_xy=True)
    back=Transformer.from_crs(32619,4326,always_xy=True)
    xyz=[project.transform(*p) for p in coords]
    cum=[0.]
    for a,b in zip(xyz,xyz[1:]):cum.append(cum[-1]+math.dist(a,b))
    if cum[-1]<=0:return [coords[0]]
    stops=[];targets=[0.]
    current=spacing_m
    while current<cum[-1]-spacing_m/2:
        targets.append(current);current+=spacing_m
    targets.append(cum[-1])
    hotspots_xy=[(project.transform(lon,lat),strength) for lon,lat,strength in (hotspots or [])]
    def interpolate(distance):
        index=max(0,min(len(cum)-2,bisect.bisect_right(cum,distance)-1))
        span=cum[index+1]-cum[index]
        t=min(1,max(0,(distance-cum[index])/span)) if span>0 else 0
        return (xyz[index][0]+t*(xyz[index+1][0]-xyz[index][0]),
                xyz[index][1]+t*(xyz[index+1][1]-xyz[index][1]))
    for idx,distance in enumerate(targets):
        if 0<idx<len(targets)-1 and hotspots_xy:
            choices=[distance-snap_search_m,distance,distance+snap_search_m]
            choices=[d for d in choices if 0<d<cum[-1]]
            def score_hotspot(d):
                p=interpolate(d)
                return sum(strength*math.exp(-math.dist(p,z)**2/(2*180**2)) for z,strength in hotspots_xy)
            distance=max(choices,key=score_hotspot)
        p=interpolate(distance)
        lon,lat=back.transform(*p)
        stops.append([round(lon,7),round(lat,7)])
    return stops

def walk_graph(graph):
    out=nx.Graph()
    for n,data in graph.nodes(data=True):out.add_node(n,x=float(data["x"]),y=float(data["y"]))
    for u,v,d in graph.edges(data=True):
        length=float(d.get("length",0))
        if length<=0:continue
        prev=out.get_edge_data(u,v)
        if prev is None or length<prev["length"]:out.add_edge(u,v,length=length)
    return out

def scorer(graph,limit_snap_m=80):
    nodes=list(graph.nodes)
    pts=[(graph.nodes[n]["x"]*math.cos(math.radians(19.8)),graph.nodes[n]["y"]) for n in nodes]
    tree=cKDTree(pts)
    def snap(coord):
        lon,lat=coord
        gap,index=tree.query((lon*math.cos(math.radians(19.8)),lat))
        distance=gap*111195
        if distance>limit_snap_m:return None,distance
        return nodes[int(index)],distance
    return snap

def build(candidates,od,walk,config,zones=None):
    if not candidates.get("features"):raise ValueError("No candidates, fail closed")
    walk=walk_graph(walk)
    snap=scorer(walk)
    scenarios=od["scenarios"]
    reference=scenarios[0]
    # Samples are sorted by relative OD flow by gravity producer.
    od_rows={}
    points={}
    for sc in scenarios:
        key=f'{sc["level"]}_beta_{sc["exponent"]}'
        od_rows[key]=sc["od"]
        for row in sc["od"]:
            points.setdefault(row["origin"],row["origin_lonlat"])
            points.setdefault(row["destination"],row["destination_lonlat"])
    endpoints={id:snap(p) for id,p in points.items()}
    top20=next(x for x in scenarios if x["level"]=="medium" and x["exponent"]==1).get("top20_zones",[])
    zone_index={z["id"]:z for z in (zones or {}).get("zones",[])}
    hotspots=[(zone_index[z["id"]]["longitude"],zone_index[z["id"]]["latitude"],
              z["endpoint_flow_proxy"]) for z in top20 if z["id"] in zone_index]
    results=[]
    for f in candidates["features"]:
        props=f["properties"];id=props["candidate_id"]
        stops=stop_points(f["geometry"]["coordinates"],sum(config["service"]["stop_spacing_m"])/2,
                          hotspots,config["service"]["stop_demand_snap_search_m"])
        snapped=[snap(stop) for stop in stops]
        seeds=[node for node,gap in snapped if node is not None]
        if seeds:
            # Store the originating stop index, not just proximity. A directed
            # street corridor must not claim reverse-direction journeys.
            reached,walk_paths=nx.multi_source_dijkstra(walk,seeds,cutoff=700,weight="length")
        else:reached={};walk_paths={}
        seed_index={}
        for index,(node,gap) in enumerate(snapped):
            if node is not None:seed_index.setdefault(node,index)
        endpoint_cost={};endpoint_stop_index={}
        for z,(n,gap) in endpoints.items():
            endpoint_cost[z]=gap+reached[n] if n in reached else None
            if n in walk_paths: endpoint_stop_index[z]=seed_index.get(walk_paths[n][0])
        route_distance=props["route_length_km_osm"]
        scores=[];incidence_by_scenario={}
        for key,rows in od_rows.items():
            served=0.;unserved=0.;current_incidence={}
            for row in rows:
                origin_dist=endpoint_cost.get(row["origin"])
                dest_dist=endpoint_cost.get(row["destination"])
                i_origin=endpoint_stop_index.get(row["origin"])
                i_dest=endpoint_stop_index.get(row["destination"])
                if (origin_dist is None or dest_dist is None or origin_dist>700 or dest_dist>700
                    or i_origin is None or i_dest is None or i_origin>=i_dest):
                    unserved+=row["relative_flow_units"];continue
                walking_factor=math.exp(-(origin_dist+dest_dist)/700)
                # Extra in-route distance cannot be known without a path assignment
                # from stop to stop; report a conservative candidate-length proxy.
                direct=max(row["straight_km"],.4)
                detour=max(1,route_distance/direct)
                penalty=math.exp(-max(0,detour-1)*.35)
                contribution=row["relative_flow_units"]*walking_factor*penalty
                served+=contribution
                current_incidence[row["origin"]+"|"+row["destination"]]=round(contribution,5)
            incidence_by_scenario[key]=current_incidence
            scores.append({"scenario":key,"relative_od_units_accessible_proxy":round(served,4),
                           "relative_od_units_inaccessible":round(unserved,4)})
        baseline=next(s for s in scores if s["scenario"]=="medium_beta_1")
        cycles=[]
        for speed in config["service"]["speed_kmh_scenarios"]:
            # No validated return trajectory. Factor 2 explicitly hypothetical.
            km=2*route_distance
            dwell=len(stops)*sum(config["service"]["dwell_seconds_assumed"])/2/60
            lights=max(1,int(route_distance*3))*sum(config["service"]["signal_delay_seconds_assumed"])/2/60
            recovery=sum(config["service"]["terminal_recovery_minutes_assumed"])/2
            cycle=60*km/speed+dwell+lights+recovery
            for headway in config["service"]["headways_min"]:
                for reserve in config["service"]["reserve_ratio_scenarios"]:
                    active=math.ceil(cycle/headway)
                    buses=math.ceil(active*(1+reserve))
                    wait_min=headway/2
                    wait_factor=math.exp(-wait_min/config["service"]["wait_decay_min_assumed"])
                    cycles.append({"speed_kmh_assumed":speed,"headway_minutes":headway,
                        "reserve_ratio_assumed":reserve,"cycle_minutes_assumed":round(cycle,2),
                        "fleet_buses_proxy":buses,"expected_random_wait_min_assumed":wait_min,
                        "score_relative_od_per_bus":round(baseline["relative_od_units_accessible_proxy"]*wait_factor/buses,5),
                        "cycle_provenance":"2x OSM outbound distance, assumed dwell/signals/terminal; return unverified"})
        results.append({"candidate_id":id,"methods":props["methods"],"geometry":f["geometry"],
           "stops":{"type":"MultiPoint","coordinates":stops},
           "stops_count":len(stops),"walk_access_method":"OSM walk graph Dijkstra; stops and H3 centroids nearest-node",
           "od_scores":scores,"captured_od_contributions_by_scenario":incidence_by_scenario,
           "service_scenarios":cycles,
           "baseline_relative_od_accessible_proxy":baseline["relative_od_units_accessible_proxy"],
           "bus_gate":"BLOQUEADO_NO_PHYSICAL_TURN_CERTIFICATION",
           "passenger_load_70_85_percent":"UNKNOWN_REQUIRES_OD_CALIBRATION",
           "source":"WorldPop + Overture + H3 synthetic demand + OSM network",
           "observed_trips":False})
    results.sort(key=lambda r:-max((x["score_relative_od_per_bus"] for x in r["service_scenarios"]),default=0))
    return {"status":"ALGORITHMIC_RANKING_EXPLORATORY",
        "ranked_candidates":results,
        "top6":[{"rank":i+1,"candidate_id":r["candidate_id"],"methods":r["methods"],
                 "score_relative_od_per_bus_best_hypothesis":max((x["score_relative_od_per_bus"] for x in r["service_scenarios"]),default=0)}
                for i,r in enumerate(results[:6])],
        "best_route_robustly_validated":False,"physical_routes_approved":0,
        "limitations":["OD scores are relative modelled flows, not passenger trips",
                       "Return length doubled without actual routing: capacity/fleet is hypothesis only",
                       "Stop count and placement are preliminary, lack curb and service access",
                       "Detour penalty is path length proxy, not OD-specific in-vehicle detour",
                       "Directional eligibility assumes closest boarded stop precedes closest alighting stop",
                       "Pedestrian edges do not verify safe crossings or complete accessibility"]}

def main():
    p=argparse.ArgumentParser()
    for n in ("candidates","od","walk","config","output"):p.add_argument("--"+n,type=Path,required=True)
    p.add_argument("--zones",type=Path,required=False)
    p.add_argument("--zones",type=Path,required=False)
    a=p.parse_args()
    report=build(json.loads(a.candidates.read_text()),json.loads(a.od.read_text()),
      ox.load_graphml(a.walk),json.loads(a.config.read_text()),
      json.loads(a.zones.read_text()) if a.zones else None)
    a.output.write_text(json.dumps(report,separators=(",",":")))
    print(json.dumps({"candidates":len(report["ranked_candidates"]),
                      "initial_top6":report["top6"],"operational_approval":0}))
if __name__=="__main__":main()
