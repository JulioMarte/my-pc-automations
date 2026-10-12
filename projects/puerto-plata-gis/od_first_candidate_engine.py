"""Generate routes only from H3 gravitational demand and directed OSM graph.

Independent strategies: high-flow shortest routes, k-shortest alternatives,
edge-flow concentration chains, marginal attraction chains. No old corridors.
No physical clearance certificate. All paths remain review-required.
"""
import argparse,json,math,hashlib
from collections import Counter
from pathlib import Path
import networkx as nx
import osmnx as ox
from scipy.spatial import cKDTree

def node_ids(g,coords):
    nodes=list(g.nodes)
    xyz=[(float(g.nodes[n]["x"]),float(g.nodes[n]["y"])) for n in nodes]
    lat0=19.78;cos=math.cos(math.radians(lat0))
    tree=cKDTree([(x*cos,y) for x,y in xyz])
    dist,indices=tree.query([(x*cos,y) for x,y in coords])
    return [(nodes[int(i)],round(float(d)*111195)) for d,i in zip(dist,indices)]

def simplest(g):
    d=nx.DiGraph()
    for u,v,attr in g.edges(data=True):
        length=float(attr.get("length",0))
        if length<=0:continue
        if not d.has_edge(u,v) or length<d[u][v]["length"]:
            d.add_edge(u,v,length=length)
    return d

def generate(graph,od,min_candidates=100,max_candidates=300,flow_limit=240):
    if min_candidates>max_candidates or max_candidates<1:raise ValueError("Candidate limits invalid")
    trials=od["experiments"]
    mid=next((t for t in trials if t["demand_scenario"]=="medium" and t["gravity_exponent"]==1.5),trials[0])
    # Never import predetermined corridor files.
    flows=mid["all_od_flows"][:flow_limit]
    coords=[f["origin_center_lonlat"] for f in flows]+[f["destination_center_lonlat"] for f in flows]
    snapped=node_ids(graph,coords)
    simple=simplest(graph)
    candidates={}
    edge_flow=Counter()
    od_pairs=[]
    def add(path,method,source_od,flow):
        if len(path)<3:return
        key=tuple(path)
        fingerprint=hashlib.sha256(",".join(map(str,key)).encode()).hexdigest()[:12]
        row=candidates.get(fingerprint)
        if row is None:
            positions=[[float(graph.nodes[n]["x"]),float(graph.nodes[n]["y"])] for n in path]
            row={"id":"OD-"+fingerprint,"node_path":list(path),"geometry":{"type":"LineString","coordinates":positions},
                 "methods":[],"supporting_od_pairs":[],"source_demand_proxy":0.0,
                 "distance_m_graph":round(sum(simple[path[i]][path[i+1]]["length"] for i in range(len(path)-1)),1),
                 "bus_physical_status":"DUDOSO","terminal_turn_verified":False,
                 "approved_for_operational_service":False}
            candidates[fingerprint]=row
        if method not in row["methods"]:row["methods"].append(method)
        if len(row["supporting_od_pairs"])<10:row["supporting_od_pairs"].append(source_od)
        row["source_demand_proxy"]+=flow
    for i,f in enumerate(flows):
        a,offset_a=snapped[i];b,offset_b=snapped[i+len(flows)]
        if a==b or offset_a>1000 or offset_b>1000:continue
        try:
            path=nx.shortest_path(simple,a,b,weight="length")
        except (nx.NetworkXNoPath,nx.NodeNotFound):continue
        if len(path)<3:continue
        weight=f["hypothetical_trips_per_day"]
        pair=[f["origin"],f["destination"]]
        add(path,"assigned_shortest_path",pair,weight)
        od_pairs.append((a,b,weight,pair))
        for u,v in zip(path,path[1:]):edge_flow[u,v]+=weight
    # Alternative method: Yen's simple k-shortest path, bounded to top OD pairs.
    for a,b,weight,pair in od_pairs[:70]:
        try:
            alternatives=nx.shortest_simple_paths(simple,a,b,weight="length")
            next(alternatives)
            for n,path in zip(range(2),alternatives):
                add(path,"k_shortest_alternative",pair,weight)
        except (nx.NetworkXNoPath,nx.NodeNotFound,StopIteration):
            continue
    # Concentrated-flow: find a high-flow road edge, extend both directions
    # greedily by aggregated OD assignment. This is graph-derived, not handmade.
    for (u,v),value in edge_flow.most_common(90):
        path=[u,v];seen=set(path)
        for _ in range(18):
            tails=[(edge_flow.get(v,w),w) for w in simple.successors(path[-1]) if w not in seen]
            if not tails:break
            score,nxt=max(tails)
            if score<=0:break
            path.append(nxt);seen.add(nxt)
        for _ in range(18):
            heads=[(edge_flow.get(w,path[0]),w) for w in simple.predecessors(path[0]) if w not in seen]
            if not heads:break
            score,prev=max(heads)
            if score<=0:break
            path.insert(0,prev);seen.add(prev)
        add(path,"edge_flow_concentration",["assigned_OD_ensemble"],value)
    # Marginal chains: start with strongest demand zone and append
    # directed shortest legs to high-potential destinations without manual anchors.
    topnodes=[]
    for a,b,weight,pair in od_pairs[:50]:topnodes.append((weight,a,b,pair))
    for weight,a,b,pair in topnodes[:30]:
        chain=[a];used={a};current=a
        for target in [b]+[q[2] for q in topnodes[:12] if q[2] not in (a,b)]:
            if target in used:continue
            try:leg=nx.shortest_path(simple,current,target,weight="length")
            except (nx.NetworkXNoPath,nx.NodeNotFound):continue
            if len(leg)<2:continue
            chain.extend(leg[1:]);used.update(leg);current=target
            if len(chain)>100:break
        add(chain,"marginal_demand_chain",pair,weight)
    selected=sorted(candidates.values(),key=lambda r:(-r["source_demand_proxy"],r["id"]))[:max_candidates]
    for r in selected:r["source_demand_proxy"]=round(r["source_demand_proxy"],3)
    return {"status":"OD_DERIVED_CANDIDATES_REQUIRE_BUS_GEOMETRY_AUDIT",
        "source_od_scenario":{"demand":mid["demand_scenario"],"exponent":mid["gravity_exponent"]},
        "candidate_count":len(selected),"target_range":[min_candidates,max_candidates],
        "target_met":min_candidates<=len(selected)<=max_candidates,
        "candidates":selected,"no_manual_routes_used":True,
        "physical_routes_approved":0,
        "limitations":["OSM graph path does not establish adequate street width, stop placement or safe turnaround",
            "One-way graph shortest paths alone ignore maneuver turn restrictions between edges",
            "Gateway OD may be outside the study graph; distant snaps are excluded",
            "Some methods produce one-way path fragments, NOT validated complete bus loops",
            "Top source OD is synthetic, not observed traffic"]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--graph",type=Path,required=True)
    p.add_argument("--od",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--geojson",type=Path,required=True)
    a=p.parse_args()
    r=generate(ox.load_graphml(a.graph),json.loads(a.od.read_text()))
    a.output.write_text(json.dumps(r,ensure_ascii=False))
    a.geojson.write_text(json.dumps({"type":"FeatureCollection","features":[{"type":"Feature","geometry":c["geometry"],"properties":{
        k:v for k,v in c.items() if k not in ("geometry","node_path","supporting_od_pairs")}} for c in r["candidates"]]},ensure_ascii=False))
    print(json.dumps({"status":r["status"],"count":r["candidate_count"],"target_met":r["target_met"]}))
if __name__=="__main__":main()
