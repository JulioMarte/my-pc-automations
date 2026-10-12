"""Genera lineas de inspeccion perpendiculares a ejes viales; no mide bordillos.

Cada transecto es una zona de busqueda, nunca ancho observado.
Distancias locales aproximadas solo para localizar muestras; usar EPSG:32619
con el raster georreferenciado antes de cualquier medicion real.
"""
import argparse, json, math
from pathlib import Path
M=111195.0

def transects(features, spacing_m=10, half_span_m=15, limit=50000):
    if not (1<=spacing_m<=100 and 1<=half_span_m<=100 and 0<limit<=1000000):
        raise ValueError("invalid transect configuration")
    results=[]
    for feat_idx, feature in enumerate(features):
        geom=feature.get("geometry",{})
        t=geom.get("type")
        chains=([geom.get("coordinates",[])] if t=="LineString" else
                geom.get("coordinates",[]) if t=="MultiLineString" else [])
        for chain in chains:
            for a,b in zip(chain,chain[1:]):
                lat=(a[1]+b[1])/2
                scale=math.cos(math.radians(lat))
                dx=(b[0]-a[0])*M*scale
                dy=(b[1]-a[1])*M
                distance=math.hypot(dx,dy)
                if distance<0.01:continue
                n=int(distance//spacing_m)
                norm=(dy/distance,-dx/distance)
                for i in range(n):
                    fraction=(i+0.5)*spacing_m/distance
                    cx=a[0]+fraction*(b[0]-a[0])
                    cy=a[1]+fraction*(b[1]-a[1])
                    lonoff=norm[0]*half_span_m/(M*scale)
                    latoff=norm[1]*half_span_m/M
                    results.append({"type":"Feature",
                        "properties":{"segment_id":str(feature.get("properties",{}).get("osmid",feat_idx)),
                            "status":"INSPECTION_TRANSECT_NOT_MEASURED",
                            "sample_spacing_m":spacing_m,
                            "search_half_span_m":half_span_m},
                        "geometry":{"type":"LineString","coordinates":[[cx-lonoff,cy-latoff],[cx+lonoff,cy+latoff]]}})
                    if len(results)>=limit:raise ValueError("Transect limit exceeded; clip area of interest")
    return {"type":"FeatureCollection","features":results}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--roads",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--spacing-m",type=float,default=10)
    p.add_argument("--half-span-m",type=float,default=15)
    a=p.parse_args()
    result=transects(json.loads(a.roads.read_text())["features"],a.spacing_m,a.half_span_m)
    a.output.write_text(json.dumps(result,ensure_ascii=False))
    print("Unmeasured transects:",len(result["features"]))

if __name__=="__main__":main()
