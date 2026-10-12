"""Exportar redes OSM dirigidas de Puerto Plata con OSMnx 2.x.

La red drive no certifica maniobrabilidad de autobuses. La red walk
representa conectividad cartografiada, no seguridad de las aceras.
"""
from __future__ import annotations
import json
from pathlib import Path
from collections import Counter
import os
import osmnx as ox
import networkx as nx

ROOT=Path(__file__).resolve().parent
# Coordenadas WGS84: oeste, sur, este, norte; perímetro de estudio urbano,
# NO límite administrativo.
BBOX=(-70.752,19.740,-70.620,19.836)
TAGS=["name","highway","oneway","lanes","width","maxwidth","maxheight","maxweight",
      "access","bus","psv","surface","sidewalk","maxspeed","bridge","tunnel"]
ox.settings.useful_tags_way=list(dict.fromkeys([*ox.settings.useful_tags_way,*TAGS]))
ox.settings.timeout=180
ox.settings.log_console=True
ox.settings.use_cache=True
ox.settings.cache_folder=str(ROOT/".osmnx-cache")

def clean(v):
    if v is None:return None
    if isinstance(v,(bool,int,float,str)):return v
    if isinstance(v,(list,tuple,set)):return "; ".join(map(str,v))
    return str(v)

def network(kind):
    graph=ox.graph_from_bbox(BBOX,network_type=kind,retain_all=True,simplify=True)
    if not graph.number_of_nodes() or not graph.number_of_edges():
        raise RuntimeError(f"Red {kind} vacía, no publicar")
    ox.save_graphml(graph,filepath=ROOT/f"{kind}.graphml")
    feats=[]
    counts=Counter()
    for u,v,k,attr in graph.edges(keys=True,data=True):
        geom=attr.get("geometry")
        if geom is not None:
            coords=[[float(x),float(y)] for x,y in geom.coords]
        else:
            a,b=graph.nodes[u],graph.nodes[v]
            coords=[[float(a["x"]),float(a["y"])],[float(b["x"]),float(b["y"])]]
        props={key:clean(attr.get(key)) for key in TAGS}
        props.update({"from_node":str(u),"to_node":str(v),"edge_key":int(k),
                      "length_m":round(float(attr.get("length",0)),1),
                      "geometry_direction":"from_node_to_to_node"})
        feats.append({"type":"Feature","properties":props,
                      "geometry":{"type":"LineString","coordinates":coords}})
        counts[str(props.get("highway") or "unknown")]+=1
    stats={"network":kind,"nodes":graph.number_of_nodes(),"directed_edges":graph.number_of_edges(),
           "weak_components":nx.number_weakly_connected_components(graph),
           "highways":dict(counts)}
    out={"type":"FeatureCollection","metadata":{"provider":"OpenStreetMap / OSMnx",
         "network":kind,"bbox_wsen":BBOX,
         "directionality":"Edges encode allowed traversal direction under OSMnx network type",
         "limitations":"OpenStreetMap attributes may be missing or wrong. DRIVE is not a bus-legal routing graph.",
         "license":"ODbL, see https://www.openstreetmap.org/copyright"},
         "features":feats}
    (ROOT/f"{kind}_network.geojson").write_text(json.dumps(out,separators=(",",":")),encoding="utf-8")
    return stats

def main():
    report={"osmnx_version":ox.__version__,"bbox_wsen":BBOX,"networks":{}}
    for typ in ("drive","walk"):report["networks"][typ]=network(typ)
    (ROOT/"network_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()
