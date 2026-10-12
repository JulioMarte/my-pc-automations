"""H3 zonification and synthetic gravity OD. NO measured passenger demand."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import h3

def h3_polygon(bbox,res):
    w,s,e,n=bbox
    return h3.polygon_to_cells(h3.LatLngPoly([(s,w),(s,e),(n,e),(n,w)]),res)

def build(population,pois,config,res=8):
    bbox=config["scope"]["bbox_wsen"]
    if res not in config["scope"]["h3_resolutions"]:raise ValueError("Unsupported resolution")
    cells={i:{"id":i,"resolution":res,"residents_estimate":0.0,"attraction_weight_proxy":0.,
              "poi_count":0,"category_counts":{},"origin_provenance":"WorldPop 2025 R2025A",
              "destination_provenance":"Overture Places; config attraction weights"}
           for i in h3_polygon(bbox,res)}
    for lat,lon,value in population["cells"]:
        if not(bbox[0]<=lon<=bbox[2] and bbox[1]<=lat<=bbox[3]):continue
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:continue
        idx=h3.latlng_to_cell(lat,lon,res)
        if idx not in cells:continue
        cells[idx]["residents_estimate"]+=value
    weights=config["attraction_weights"]
    for feat in pois["features"]:
        geo=feat.get("geometry") or {}
        if geo.get("type")!="Point":continue
        lon,lat=geo["coordinates"][:2]
        if not(bbox[0]<=lon<=bbox[2] and bbox[1]<=lat<=bbox[3]):continue
        idx=h3.latlng_to_cell(lat,lon,res)
        if idx not in cells:continue
        category=str((feat.get("properties") or {}).get("type","other"))
        if category not in weights:raise ValueError(f"Unconfigured POI category: {category}")
        cells[idx]["attraction_weight_proxy"]+=weights[category]
        cells[idx]["poi_count"]+=1
        counts=cells[idx]["category_counts"]
        counts[category]=counts.get(category,0)+1
    for i,c in cells.items():
        lat,lon=h3.cell_to_latlng(i)
        c["latitude"]=lat;c["longitude"]=lon
        c["residents_estimate"]=round(c["residents_estimate"],3)
    return {"status":"SYNTHETIC_H3_ZONES_NOT_FULL_URBAN_BOUNDARY_VALIDATED",
            "resolution":res,"scope":bbox,"scope_status":config["scope"]["urban_boundary_status"],
            "sources":config["sources"],"zones":sorted(cells.values(),key=lambda x:x["id"])}

def haversine(a,b):
    lat1,lon1=map(math.radians,a);lat2,lon2=map(math.radians,b)
    dlat=lat2-lat1;dlon=lon2-lon1
    t=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 12742*math.asin(min(1,math.sqrt(t)))

def demand(zones,config,limit=2000):
    cfg=config["gravity"]
    available=[z for z in zones["zones"] if z["attraction_weight_proxy"]>0]
    sources=[z for z in zones["zones"] if z["residents_estimate"]>0]
    for g in cfg["external_gateways"]:
        sources.append({"id":g["id"],"latitude":g["lat"],"longitude":g["lon"],
                        "residents_estimate":g["production_assumption"],"external":True})
    if not sources or not available:raise ValueError("No OD producers/attractors")
    scenarios=[]
    for label,factor in cfg["scenarios"].items():
      for exponent in cfg["distance_decay_exponents"]:
        rows=[]
        for origin in sources:
            candidates=[]
            for dest in available:
                if origin["id"]==dest["id"]:continue
                distance=max(cfg["distance_floor_km"],haversine(
                    (origin["latitude"],origin["longitude"]),(dest["latitude"],dest["longitude"])))
                gravity=dest["attraction_weight_proxy"]/(distance**exponent)
                if gravity>0:candidates.append((dest,gravity,distance))
            total=sum(x[1] for x in candidates)
            if not total:continue
            for dest,strength,distance in candidates:
                units=origin["residents_estimate"]*factor*strength/total
                if units<=0:continue
                rows.append({"origin":origin["id"],"destination":dest["id"],
                    "origin_lonlat":[origin["longitude"],origin["latitude"]],
                    "destination_lonlat":[dest["longitude"],dest["latitude"]],
                    "straight_km":round(distance,3),"relative_flow_units":round(units,6),
                    "external_origin_assumed":bool(origin.get("external",False)),
                    "mode":"SYNTHETIC_RELATIVE_UNITS_NOT_OBSERVED_TRIPS"})
        rows.sort(key=lambda x:x["relative_flow_units"],reverse=True)
        # top-N truncation explicitly disclosed; not complete OD assignment.
        zones_sum={}
        for r in rows:
            for k in ("origin","destination"):
                zone=r[k]
                zones_sum[zone]=zones_sum.get(zone,0.)+r["relative_flow_units"]
        top_zones=sorted(zones_sum.items(),key=lambda x:-x[1])[:20]
        scenarios.append({"level":label,"exponent":exponent,
            "generated_pairs":len(rows),"published_pairs":min(len(rows),limit),
            "total_generated_relative_flow":round(sum(r["relative_flow_units"] for r in rows),3),
            "od":rows[:limit],"top20_zones":[{"id":i,"endpoint_flow_proxy":round(v,3)} for i,v in top_zones],
            "truncated_top_od":len(rows)>limit})
    baseline=next(x for x in scenarios if x["level"]=="medium" and x["exponent"]==cfg["distance_decay_exponents"][0])
    lines={"type":"FeatureCollection","metadata":{"source":"Synthetic gravity OD",
        "counts_are_not_observed":True,"display":"top OD, baseline medium exponent"},
        "features":[{"type":"Feature","geometry":{"type":"LineString",
          "coordinates":[r["origin_lonlat"],r["destination_lonlat"]]},
          "properties":{k:r[k] for k in ("origin","destination","relative_flow_units","external_origin_assumed")}}
          for r in baseline["od"]]}
    return {"status":"GRAVITY_OD_UNCALIBRATED","scenarios":scenarios,
            "gateways_are_assumptions":True,"provenance":config["sources"],
            "gravity_equation":"OD_ij = scenario_factor * P_i * (A_j/d_ij^beta) / sum_j(A_j/d_ij^beta)",
            "count_interpretation":"RELATIVE_SYNTHETIC_FLOW_NOT_OBSERVED_TRIPS"},lines

def main():
    p=argparse.ArgumentParser()
    for n in ("population","pois","config","output","desires"):
        p.add_argument("--"+n,type=Path,required=True)
    p.add_argument("--zones",type=Path,required=True)
    a=p.parse_args()
    cfg=json.loads(a.config.read_text())
    pop=json.loads(a.population.read_text());pois=json.loads(a.pois.read_text())
    zone_data=build(pop,pois,cfg,8)
    a.zones.write_text(json.dumps(zone_data))
    od,lines=demand(zone_data,cfg)
    a.output.write_text(json.dumps(od))
    a.desires.write_text(json.dumps(lines))
    print(json.dumps({"zones":len(zone_data["zones"]),"scenarios":len(od["scenarios"]),
                      "baseline_pairs":len(lines["features"])}))
if __name__=="__main__":main()
