"""Independent OSM directed-road candidate generators; no legacy corridors.

Candidate routes are algorithmic graph paths. OSM missing geometry means
physical Yutong clearance DUBIOUS, never VIABLE or APPROVED.
"""
from __future__ import annotations
import argparse,json,math,heapq,re
from pathlib import Path
from collections import defaultdict
import networkx as nx
from scipy.spatial import cKDTree

def numeric_limit(value):
    if value is None:return None
    text=str(value).strip().lower()
    if not text or text in {'none','nan','unknown'} or 'ft' in text or '\\u2032' in text:return None
    match=re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*(?:m|metres?|meters?)?',text)
    return float(match.group(1)) if match else None

def road_graph(graph,vehicle=None):
    out=nx.DiGraph()
    for n,d in graph.nodes(data=True):
        out.add_node(n,lon=float(d["x"]),lat=float(d["y"]))
    for u,v,k,data in graph.edges(keys=True,data=True):
        length=float(data.get("length") or 0)
        if length<=0:continue
        blocked=str(data.get("bus","")).lower() in {"no","private"} or str(data.get("access","")).lower()=="no"
        blocked=blocked or str(data.get("highway","")).lower() in {"footway","path","steps","pedestrian","cycleway"}
        if vehicle:
            width=numeric_limit(data.get("maxwidth"))
            height=numeric_limit(data.get("maxheight"))
            # Conflicting OSM restrictions block this graph edge; tag presence
            # does not validate street clearance where attributes are absent.
            if width is not None and width<vehicle["width_m"]:blocked=True
            if height is not None and height<min(vehicle["height_reference_range_m"]):blocked=True
        if blocked:continue
        existing=out.get_edge_data(u,v)
        if existing is None or length<existing["length"]:
            out.add_edge(u,v,length=length,
                maxheight=data.get("maxheight"),maxwidth=data.get("maxwidth"),
                surface=data.get("surface"),bus=data.get("bus"),source="OSM")
    return out

def nearest_nodes(g,od):
    nodes=list(g.nodes)
    xy=[(g.nodes[n]["lon"]*math.cos(math.radians(19.8)),g.nodes[n]["lat"]) for n in nodes]
    tree=cKDTree(xy)
    mapped={}
    for row in od:
        for key in ("origin","destination"):
            cid=row[key]
            if cid not in mapped:
                coord=row["origin_lonlat"] if key=="origin" else row["destination_lonlat"]
                query=[coord[0]*math.cos(math.radians(19.8)),coord[1]]
                mapped[cid]=nodes[int(tree.query(query)[1])]
    return mapped

def edge_signature(path):
    return tuple((str(u),str(v)) for u,v in zip(path,path[1:]))

def generate(graph,od,config):
    g=road_graph(graph,config["vehicle"])
    if not g.number_of_edges():raise ValueError("No drivable OSM edges")
    base=next(s for s in od["scenarios"] if s["level"]=="medium" and s["exponent"]==config["gravity"]["distance_decay_exponents"][0])
    flows=base["od"][:config["generation"]["seed_top_od"]]
    nodes=nearest_nodes(g,flows)
    registry={}
    flow_edges=defaultdict(float)
    diagnostics={"od_pairs_attempted":0,"od_pairs_unreachable":0,"paths_generated_by_method":{}}
    goal=config["generation"]
    def submit(path,method,flow):
        if len(path)<3 or len(set(path))<3:return
        length=sum(g[u][v]["length"] for u,v in zip(path,path[1:]))/1000
        if not goal["min_route_km"]<=length<=goal["max_route_km"]:return
        signature=edge_signature(path)
        reverse_signature=edge_signature(path[::-1])
        key=min(signature,reverse_signature)
        # identical street sequence from different origin/OD method is one candidate.
        if key in registry:
            registry[key]["methods"].add(method)
            registry[key]["support_flow_proxy"]+=flow
            return
        registry[key]={"nodes":path,"length_km":round(length,3),
                       "methods":{method},"support_flow_proxy":flow}
        diagnostics["paths_generated_by_method"][method]=diagnostics["paths_generated_by_method"].get(method,0)+1
    for row in flows:
        a,b=nodes[row["origin"]],nodes[row["destination"]]
        if a==b:continue
        diagnostics["od_pairs_attempted"]+=1
        try:path=nx.shortest_path(g,a,b,weight="length")
        except (nx.NetworkXNoPath,nx.NodeNotFound):
            diagnostics["od_pairs_unreachable"]+=1;continue
        for edge in zip(path,path[1:]):flow_edges[edge]+=row["relative_flow_units"]
        submit(path,"OD_SHORTEST",row["relative_flow_units"])
        try:
            alternatives=nx.shortest_simple_paths(g,a,b,weight="length")
            for k,path in zip(range(goal["k_paths_per_od"]),alternatives):
                submit(path,"K_SHORTEST",row["relative_flow_units"])
        except (nx.NetworkXNoPath,nx.NodeNotFound):
            pass
    # Independent method A: accumulated link flow -> greedily extend adjacent
    # edges with highest observed MODELLED link-flow support.
    strongest=sorted(flow_edges,key=lambda e:-flow_edges[e])[:goal["chain_starts"]]
    for start in strongest:
        path=[start[0],start[1]]
        used=set(path)
        for _ in range(goal["chain_max_waypoints"]*2):
            node=path[-1]
            neighbors=[(flow_edges.get((node,n),0),n) for n in g.successors(node) if n not in used]
            if not neighbors:break
            weight,next_node=max(neighbors,key=lambda z:z[0])
            if weight<=0:break
            path.append(next_node);used.add(next_node)
            submit(path[:],"FLOW_ACCUMULATION",weight)
    # Independent method C: greedy demand gain along paths from leading OD
    # origin, picking reachable next destination with strongest unused flow.
    by_origin=defaultdict(list)
    for r in flows:by_origin[r["origin"]].append(r)
    for origin,items in sorted(by_origin.items(),key=lambda x:-sum(i["relative_flow_units"] for i in x[1]))[:goal["chain_starts"]]:
        start=nodes[origin];path=[start];visited={start}
        for item in sorted(items,key=lambda z:-z["relative_flow_units"])[:goal["chain_max_waypoints"]]:
            dest=nodes[item["destination"]]
            try:leg=nx.shortest_path(g,path[-1],dest,weight="length")
            except (nx.NetworkXNoPath,nx.NodeNotFound):continue
            if len(path)+len(leg)>110:continue
            path.extend(leg[1:])
            if len(path)>=3:submit(path[:],"GREEDY_OD_CHAIN",item["relative_flow_units"])
    ordered=sorted(registry.values(),key=lambda r:(-r["support_flow_proxy"],r["length_km"]))
    ordered=ordered[:goal["target_max"]]
    features=[]
    for i,r in enumerate(ordered):
        coords=[[g.nodes[n]["lon"],g.nodes[n]["lat"]] for n in r["nodes"]]
        features.append({"type":"Feature","properties":{"candidate_id":f"AUTO-{i+1:03d}",
          "methods":sorted(r["methods"]),"support_flow_proxy":round(r["support_flow_proxy"],4),
          "route_length_km_osm":r["length_km"],
          "bus_turn_status":"DUDOSO_UNSURVEYED",
          "terminal_return_status":"DUDOSO_UNSURVEYED",
          "physical_approval":False,
          "provenance":"Directed OSM graph and synthetic WorldPop/Overture gravity OD"},
          "geometry":{"type":"LineString","coordinates":coords}})
    status="EXPLORATORY_CANDIDATES" if len(features)>=goal["target_min"] else "INSUFFICIENT_CANDIDATE_DIVERSITY"
    return {"status":status,"target_min":goal["target_min"],"target_max":goal["target_max"],
       "generated_unique":len(features),"diagnostics":diagnostics,
       "limitations":["Turn swept path not evaluated","Terminal turnaround not verified",
                      "Shortest path graph does not encode all vehicle restrictions",
                      "Candidate lines from OSM nodes, not curb-aligned bus movements"],
       "type":"FeatureCollection","features":features}

def main():
    p=argparse.ArgumentParser()
    for n in ("graph","od","config","output"):p.add_argument("--"+n,type=Path,required=True)
    a=p.parse_args()
    import osmnx as ox
    g=ox.load_graphml(a.graph)
    od=json.loads(a.od.read_text());cfg=json.loads(a.config.read_text())
    out=generate(g,od,cfg)
    a.output.write_text(json.dumps(out,separators=(",",":")))
    print(json.dumps({"status":out["status"],"candidates":out["generated_unique"],"methods":out["diagnostics"]["paths_generated_by_method"]}))
if __name__=="__main__":main()
