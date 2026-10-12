"""OD-first H3 baseline: NO reuse of L1, old candidate IDs or their alignments.

WorldPop pixel centers are binned into H3; Overture Point POIs are
weighted by CONFIG, not by hard-coded coefficients. Cells within the
configured bbox represent a boundary proxy, not a mapped urban outline.
"""
import argparse,json,math
from pathlib import Path
import h3

def build(population,destinations,config):
    bbox=config["urban_extent_bbox_lonlat"]
    resolutions=config["h3_resolutions"]
    weights=config["poi_category_weights"]
    if not all(x in (8,9) for x in resolutions):raise ValueError("Only H3 8/9 allowed")
    outputs={}
    for resolution in resolutions:
        cells={}
        def record(lat,lon):
            id=h3.latlng_to_cell(lat,lon,resolution)
            if id not in cells:
                y,x=h3.cell_to_latlng(id)
                cells[id]={"id":id,"resolution":resolution,"center":[round(x,7),round(y,7)],
                           "worldpop_residents_estimated":0.0,"poi_weight_proxy":0.0,
                           "poi_count":0,"poi_types":{}}
            return cells[id]
        # Raster cell-to-H3 centroid allocation is a proxy; boundary pixels are not clipped.
        for point in population["cells"]:
            lat,lon,v=point
            if not (bbox[0]<=lon<=bbox[2] and bbox[1]<=lat<=bbox[3]) or not math.isfinite(v) or v<=0:continue
            record(lat,lon)["worldpop_residents_estimated"]+=float(v)
        for f in destinations["features"]:
            g=f.get("geometry") or {}
            if g.get("type")!="Point":continue
            lon,lat=g["coordinates"][:2]
            if not (bbox[0]<=lon<=bbox[2] and bbox[1]<=lat<=bbox[3]):continue
            typ=str((f.get("properties") or {}).get("type","other")).lower()
            c=record(lat,lon)
            c["poi_count"]+=1
            c["poi_weight_proxy"]+=float(weights.get(typ,weights["other"]))
            c["poi_types"][typ]=c["poi_types"].get(typ,0)+1
        outputs[str(resolution)]=[]
        for id,c in sorted(cells.items()):
            c["worldpop_residents_estimated"]=round(c["worldpop_residents_estimated"],3)
            c["poi_weight_proxy"]=round(c["poi_weight_proxy"],3)
            outputs[str(resolution)].append(c)
    return {"status":"H3_POPULATION_POI_PROXIES_UNCALIBRATED",
        "boundary_status":config["urban_boundary"],"h3_resolutions":resolutions,
        "primary_resolution":config["primary_resolution"],
        "h3_cells":outputs,"origin_source":"WorldPop pixel centers",
        "attraction_source":"Overture POI classification",
        "no_prior_corridors_used":True,"provenance":config["sources"],
        "limitations":["WorldPop cells assigned to H3 by pixel center; no areal split",
        "POI weights are hypotheses; no employment or observed trip counts",
        "Study boundary is a bbox proxy, not a verified urban footprint"]}

def cells_geojson(result):
    features=[]
    for res,group in result["h3_cells"].items():
        for c in group:
            boundary=h3.cell_to_boundary(c["id"])
            coords=[[lon,lat] for lat,lon in boundary]
            coords.append(coords[0])
            features.append({"type":"Feature","geometry":{"type":"Polygon","coordinates":[coords]},
                "properties":{k:v for k,v in c.items() if k!="poi_types"}})
    return {"type":"FeatureCollection","features":features}

def main():
    a=argparse.ArgumentParser()
    for k in ("population","destinations","config","output","geojson"):a.add_argument("--"+k,type=Path,required=True)
    o=a.parse_args()
    r=build(json.loads(o.population.read_text()),json.loads(o.destinations.read_text()),json.loads(o.config.read_text()))
    o.output.write_text(json.dumps(r,ensure_ascii=False))
    o.geojson.write_text(json.dumps(cells_geojson(r),ensure_ascii=False))
    print(json.dumps({"status":r["status"],"cell_counts":{x:len(y) for x,y in r["h3_cells"].items()}}))
if __name__=="__main__":main()
