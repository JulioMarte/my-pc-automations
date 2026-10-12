"""Historical L1 control scored AFTER algorithmic search; never seeded or fixed."""
import argparse,json,math
from pathlib import Path
from pyproj import Transformer
import osmnx as ox
from score_candidates import build

def compare(legacy_fc,scored,od,walk,config,zones=None):
    lines=[f["geometry"]["coordinates"] for f in legacy_fc.get("features",[])
           if f.get("geometry",{}).get("type")=="LineString"]
    if not lines:raise ValueError("Historical L1 lacks a route polyline")
    coords=lines[0]
    proj=Transformer.from_crs(4326,32619,always_xy=True)
    xy=[proj.transform(*p) for p in coords]
    length=sum(math.dist(a,b) for a,b in zip(xy,xy[1:]))/1000
    if length<=0:raise ValueError("L1 length missing")
    record={"features":[{"properties":{"candidate_id":"CONTROL_L1_NOT_A_CANDIDATE",
          "methods":["HISTORICAL_CONTROL_ONLY"],"route_length_km_osm":round(length,3)},
          "geometry":{"type":"LineString","coordinates":coords}}]}
    evaluated=build(record,od,walk,config,zones)
    result=evaluated["ranked_candidates"][0]
    score=max(v["score_relative_od_per_bus"] for v in result["service_scenarios"])
    scores=[max(v["score_relative_od_per_bus"] for v in r["service_scenarios"])
            for r in scored["ranked_candidates"]]
    rank=1+sum(x>score for x in scores)
    return {"status":"HISTORICAL_L1_CONTROL_POSTHOC_ONLY",
        "control_id":"CONTROL_L1_NOT_A_CANDIDATE",
        "hypothetical_relative_od_per_bus":score,
        "posthoc_rank_among_new_300_plus_control":rank,
        "algorithmic_routes_compared":len(scores),
        "l1_was_seeded_or_required":False,
        "operationally_approved":False,
        "warnings":["Legacy control uses OSRM car route and not verified Yutong clearance",
                    "Comparison uses same scenario hypothesis and OSM walk graph, not observed OD"]}

def main():
    p=argparse.ArgumentParser()
    for n in ("legacy","scored","od","walk","config","output"):p.add_argument("--"+n,type=Path,required=True)
    p.add_argument("--zones",type=Path,required=False)
    a=p.parse_args()
    result=compare(json.loads(a.legacy.read_text()),json.loads(a.scored.read_text()),
        json.loads(a.od.read_text()),ox.load_graphml(a.walk),json.loads(a.config.read_text()),
        json.loads(a.zones.read_text()) if a.zones else None)
    a.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
if __name__=="__main__":main()
