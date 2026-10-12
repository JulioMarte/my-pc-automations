"""Verify live Valhalla street geometry and publish geometry-ready GeoJSON.

Actual graph polyline is not swept-path, curb geometry or bus stop validation.
"""
import argparse,json,math
from pathlib import Path

def summarize(report):
    routes=[]
    geo=[]
    for route in report.get("routes",[]):
        record={"id":route["id"],"directions":{},"physically_approved":False}
        for direction in ("outbound","inbound"):
            leg=route.get(direction) or {}
            shape=leg.get("road_shape") or {}
            coords=(shape.get("geometry") or {}).get("coordinates") or []
            good=(leg.get("status")=="routed" and shape.get("status")=="ROAD_GRAPH_SHAPE_NOT_SWEPT_PATH"
                  and len(coords)>=2 and all(isinstance(p,list) and len(p)>=2 and all(math.isfinite(v) for v in p[:2]) for p in coords))
            record["directions"][direction]={"routed":leg.get("status")=="routed",
                "shape_available":bool(good),"distance_km":leg.get("distance_km"),
                "time_seconds":leg.get("time_seconds"),"vertex_count":len(coords)}
            if good:
                geo.append({"type":"Feature","properties":{"candidate":route["id"],
                    "direction":direction,"distance_km":leg["distance_km"],
                    "source":"Valhalla graph tiles from OSM","physical_turn_approved":False},
                    "geometry":{"type":"LineString","coordinates":coords}})
        record["both_directions_with_shapes"]=all(record["directions"][d]["shape_available"] for d in ("outbound","inbound"))
        routes.append(record)
    return ({"status":"ROUTED_GEOMETRY_QA_NOT_PHYSICAL_APPROVAL",
             "routes_checked":len(routes),
             "routes_with_both_shapes":sum(r["both_directions_with_shapes"] for r in routes),
             "directional_shapes":len(geo),
             "bus_turns_approved":0,"routes":routes,
             "limitations":["Valhalla path between terminal anchors does not force serving intermediate stops",
                            "Bus costing does not verify street widths, swept path or legal terminal turnaround"]},
            {"type":"FeatureCollection","features":geo})

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--routing",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    p.add_argument("--geojson",type=Path,required=True)
    args=p.parse_args()
    result,geo=summarize(json.loads(args.routing.read_text()))
    args.report.write_text(json.dumps(result,indent=2,ensure_ascii=False))
    args.geojson.write_text(json.dumps(geo,separators=(",",":")))
    print(json.dumps({"routes":result["routes_checked"],"with_both_shapes":result["routes_with_both_shapes"],"geometry_features":len(geo)}))
if __name__=="__main__":main()
