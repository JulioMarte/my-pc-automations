"""Revisión geométrica preliminar de rutas con Yutong de 12.17 m."""
import json, math, argparse
from pathlib import Path

def screen(features, threshold=40):
    risks=[]
    for feature in features:
        if feature.get("geometry",{}).get("type")!="MultiPoint":continue
        coords=feature["geometry"]["coordinates"]
        visited=set()
        for i in range(1,len(coords)-1):
            a,b,c=coords[i-1:i+2]
            k=(round(b[0],6),round(b[1],6))
            lat=math.radians(b[1])
            u=((b[0]-a[0])*math.cos(lat),b[1]-a[1])
            v=((c[0]-b[0])*math.cos(lat),c[1]-b[1])
            m,n=math.hypot(*u),math.hypot(*v)
            if min(m,n)<1e-10:continue
            d=round(math.degrees(math.acos(max(-1,min(1,(u[0]*v[0]+u[1]*v[1])/(m*n))))),1)
            if d<threshold or k in visited:continue
            visited.add(k)
            risks.append({"candidate":feature["properties"]["id"],"latitude":b[1],"longitude":b[0],
                          "heading_change_deg":d,"vehicle":"Yutong ZK6126HG",
                          "turn_circle_reference_m":20.5,"status":"PENDIENTE_VERIFICACION"})
    return {"status":"EXPLORATORIO_SIN_APROBACION_FISICA",
            "source":"https://www.yutong.com.kz/products/ZK6126HG-param.shtml",
            "sensitivity_turn_circle_m":[20.5,21,21.5],
            "note":"No son giros de calzada ni simulación de barrido; faltan anchos y obstáculos.",
            "risks":risks}

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--input",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    x=a.parse_args()
    result=screen(json.loads(x.input.read_text())["features"])
    x.output.write_text(json.dumps(result,indent=2))
    print("Candidate waypoint bends:",len(result["risks"]))

if __name__=="__main__":main()
