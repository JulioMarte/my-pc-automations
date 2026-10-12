"""Gravity-model desire lines with low/medium/high and sensitivity exponents.

All trip volumes are HYPOTHETICAL propensity flows, not observed OD.
External gateways are modeled as explicit assumptions; no origin route is fixed.
"""
import argparse,json,math
from pathlib import Path

def haversine(a,b):
    rad=math.pi/180
    p1,p2=a[1]*rad,b[1]*rad
    h=math.sin((p2-p1)/2)**2+math.cos(p1)*math.cos(p2)*math.sin((b[0]-a[0])*rad/2)**2
    return 12742*math.asin(min(1,math.sqrt(h)))

def model(zones,config):
    cells=zones["h3_cells"][str(config["primary_resolution"])]
    geo=config["gravity"]
    destinations=sorted((c for c in cells if c["poi_weight_proxy"]>0),
                       key=lambda c:-c["poi_weight_proxy"])
    if not destinations:raise ValueError("No mapped destination attraction; demand cannot be derived")
    # Keep all origin cells; sparse destination truncation declared per origin.
    origins=[{"id":c["id"],"center":c["center"],"production_base":c["worldpop_residents_estimated"],
              "external":False} for c in cells if c["worldpop_residents_estimated"]>0]
    origins.extend({"id":"GATE_"+x["name"],"center":[x["lon"],x["lat"]],
                    "production_base":float(x["external_trip_weight_assumed"]),"external":True}
                   for x in config["gateway_zones"])
    if any(x["production_base"]<0 for x in origins):raise ValueError("Negative origin mass")
    experiments=[]
    for name,scenario in geo["demand_scenarios"].items():
        for beta in geo["exponents"]:
            if beta<=0:raise ValueError("Gravity exponent must be positive")
            flows=[]
            for origin in origins:
                mass=origin["production_base"]*scenario["trips_per_resident_day_assumed"]
                if mass<=0:continue
                possible=[]
                for dest in destinations:
                    if dest["id"]==origin["id"]:continue
                    dist=haversine(origin["center"],dest["center"])
                    score=dest["poi_weight_proxy"]/(dist+geo["distance_offset_km"])**beta
                    if score>0:possible.append((score,dist,dest))
                # Truncation is model simplification, not a claim that farther trips do not exist.
                possible.sort(key=lambda v:-v[0])
                selected=possible[:geo["max_destination_cells_per_origin"]]
                denominator=sum(q[0] for q in selected)
                for score,dist,dest in selected:
                    volume=mass*score/denominator if denominator else 0
                    if volume>0:
                        flows.append({"origin":origin["id"],"destination":dest["id"],
                           "origin_center_lonlat":origin["center"],"destination_center_lonlat":dest["center"],
                           "distance_km_straight":round(dist,3),
                           "hypothetical_trips_per_day":round(volume,5),
                           "external_gateway_assumption":origin["external"]})
            flows.sort(key=lambda x:-x["hypothetical_trips_per_day"])
            totals={}
            for f in flows:
                totals[f["origin"]]=totals.get(f["origin"],0)+f["hypothetical_trips_per_day"]
                totals[f["destination"]]=totals.get(f["destination"],0)+f["hypothetical_trips_per_day"]
            experiments.append({"demand_scenario":name,"gravity_exponent":beta,
                "total_hypothetical_od_trips":round(sum(x["hypothetical_trips_per_day"] for x in flows),2),
                "unique_od_pairs":len(flows),"top_20_cells_by_through_flow":[
                    {"zone":k,"endpoint_flow_proxy":round(v,2)} for k,v in sorted(totals.items(),key=lambda x:-x[1])[:20]],
                "top_100_desire_lines":flows[:geo["top_desire_lines"]],
                "all_od_flows":flows})
    return {"status":"SYNTHETIC_GRAVITY_OD_NO_CALIBRATION","observed_trips":False,
            "no_hand_selected_corridors":True,"experiments":experiments,
            "gateway_zones_assumed":config["gateway_zones"],
            "production_source":"WorldPop rescaled by trip propensity hypothesis",
            "attraction_source":"Overture category weighted POIs",
            "distance_model":"centroid great-circle decay, NOT road travel time",
            "limitations":["OD does not represent observed commuters, commercial activity or traffic",
                 "Gateway points and trip weights are unverified assumptions",
                 "Truncated destination choice set introduces selection bias",
                 "No within-cell OD; walking, mode share, trip purpose or traffic assignment"]}

def desire_geojson(report):
    features=[]
    for trial in report["experiments"]:
        for f in trial["top_100_desire_lines"]:
            features.append({"type":"Feature","geometry":{"type":"LineString",
                "coordinates":[f["origin_center_lonlat"],f["destination_center_lonlat"]]},
                "properties":{"demand_scenario":trial["demand_scenario"],"exponent":trial["gravity_exponent"],
                  "estimated_trips_hypothetical":f["hypothetical_trips_per_day"],
                  "external_gateway_assumption":f["external_gateway_assumption"]}})
    return {"type":"FeatureCollection","features":features}

def main():
    a=argparse.ArgumentParser()
    for n in ("zones","config","output","geojson"):a.add_argument("--"+n,type=Path,required=True)
    x=a.parse_args()
    result=model(json.loads(x.zones.read_text()),json.loads(x.config.read_text()))
    x.output.write_text(json.dumps(result,ensure_ascii=False))
    x.geojson.write_text(json.dumps(desire_geojson(result),ensure_ascii=False))
    print(json.dumps({"experiments":len(result["experiments"]),
                      "top_count":len(result["experiments"][0]["top_20_cells_by_through_flow"])}))
if __name__=="__main__":main()
