from pathlib import Path
import json, math, urllib.request
ROOT=Path(__file__).resolve().parent
start=(-70.72366,19.80523)  # UASD Puerto Plata, OSM/mapcarta
end=(-70.6440564,19.7566575)  # Solarzentrum/Oasis, captura usuario
url=f"https://router.project-osrm.org/route/v1/driving/{start[0]},{start[1]};{end[0]},{end[1]}?overview=full&geometries=geojson&steps=false"
req=urllib.request.Request(url,headers={"User-Agent":"PuertoPlataMobilityStudy/0.1 (public github research demo)"})
with urllib.request.urlopen(req,timeout=40) as r: js=json.load(r)
if js.get("code")!="Ok" or not js.get("routes"): raise RuntimeError("No pudo calcularse el corredor vial")
route=js["routes"][0]
coords=route["geometry"]["coordinates"]
distance=route["distance"]
if not 7000<distance<30000: raise RuntimeError(f"Ruta fuera de rango: {distance} m")
def hav(a,b):
    r=6371008.8;lat1,lat2=math.radians(a[1]),math.radians(b[1]);dlat=lat2-lat1;dlon=math.radians(b[0]-a[0]);x=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2;return 2*r*math.asin(min(1,math.sqrt(x)))
cum=[0.0]
for a,b in zip(coords,coords[1:]):cum.append(cum[-1]+hav(a,b))
n=max(2,round(cum[-1]/500)+1)
points=[]
for i in range(n):
    target=i*cum[-1]/(n-1)
    j=next((x for x in range(1,len(cum)) if cum[x]>=target),len(cum)-1)
    frac=(target-cum[j-1])/max(.0001,cum[j]-cum[j-1])
    a,b=coords[j-1],coords[j]
    pt=[round(a[0]+frac*(b[0]-a[0]),6),round(a[1]+frac*(b[1]-a[1]),6)]
    points.append({"type":"Feature","properties":{"kind":"stop","name":("UASD" if i==0 else "Oasis / Playa Dorada" if i==n-1 else f"Parada propuesta {i:02}"),"provisional":True},"geometry":{"type":"Point","coordinates":pt}})
fc={"type":"FeatureCollection","metadata":{"source":"OSRM public routing service, OpenStreetMap network","provisional":True,"distance_m":round(distance),"duration_s_car_light":round(route["duration"]),"note":"Las paradas equidistantes son simulaciones, no ubicaciones aprobadas ni verificadas. Ruta vial para automóvil; confirmar circulación de bus."},"features":[{"type":"Feature","properties":{"kind":"route","name":"Trazado vial preliminar UASD–Oasis","provisional":True},"geometry":{"type":"LineString","coordinates":coords}}]+points}
(ROOT/"initial_route.geojson").write_text(json.dumps(fc,separators=(",",":")))
print("OSRM route km:",round(distance/1000,2),"stops candidate",n)
