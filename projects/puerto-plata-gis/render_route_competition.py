"""Build portable offline comparison dashboard from measured GIS outputs."""
import json,html
from pathlib import Path
ROOT=Path(__file__).resolve().parent
r=json.loads((ROOT/"route_competition.json").read_text())
features=json.loads((ROOT/"discovered_routes.geojson").read_text())["features"]
payload=json.dumps({"results":r,"geometry":features},ensure_ascii=False).replace("</","<\\/")
out=ROOT/"Competencia_Rutas_Puerto_Plata.html"
page='''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Puerto Plata · Competidoras y redes</title><style>
*{box-sizing:border-box}body{margin:0;background:#091923;color:#e7f0f4;font:15px system-ui}header{padding:20px 24px;border-bottom:1px solid #355666}h1{margin:0;font-size:23px}p{color:#adc7d3}main{display:grid;grid-template-columns:390px 1fr;height:calc(100vh - 105px)}aside{overflow:auto;padding:16px;background:#122e3e}section{border:1px solid #31586b;padding:12px;border-radius:10px;margin-bottom:12px}#map{width:100%;height:100%;background:#152f39}label{display:block;margin:7px 0}button,select{background:#234e61;border:1px solid #52778a;padding:7px;color:white;border-radius:8px;max-width:100%;cursor:pointer}.stats{font-size:13px}.stats b{font-size:22px;display:block}.tag{font-size:12px;color:#ffc97a}table{border-collapse:collapse;width:100%;font-size:12px}td,th{padding:7px 4px;text-align:left;border-bottom:1px solid #355666}tr:hover{background:#214557;cursor:pointer}svg{width:100%;height:100%;touch-action:none}.legend{font-size:11px;color:#b4ced5} @media(max-width:850px){main{display:block;height:auto}aside{max-height:70vh}#map{height:65vh}}
</style></head><body><header><h1>Puerto Plata · Competencia de corredores</h1><p>Escenarios experimentales: cobertura caminable, red vial dirigida y solapamiento entre rutas. No se han validado giros ni circulación de autobuses.</p></header><main><aside>
<section><b>Escenario para visualizar</b><label for="route">Corredor individual</label><select id="route"></select><label for="network">Combinación L1 + complementarias</label><select id="network"></select><p class="stats" id="summary"></p><p class="tag">Una puntuación alta NO demuestra un viaje rápido o una ruta viable. Las maniobras, los transbordos y la demanda están pendientes.</p></section>
<section><b>Top competidoras frente a L1</b><table><thead><tr><th>Ruta</th><th>Nuevos habitantes*</th><th>POI*</th><th>Km ciclo</th></tr></thead><tbody id="top"></tbody></table></section>
<section><b>Datos del estudio</b><p class="legend" id="facts"></p><p class="legend">* Población WorldPop modelada y POI Overture en 500 m de red peatonal aproximada. Se cuentan una sola vez para cada combinación. Sin datos observados de pasajeros.</p></section>
</aside><div id="map"><svg id="canvas" viewBox="0 0 900 610" preserveAspectRatio="xMidYMid meet" aria-label="Esquema geográfico offline de puntos de parada"><g id="routes"></g></svg></div></main><script id="data" type="application/json">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('data').textContent),r=data.results,feats=data.geometry;
const routeSel=document.getElementById('route'),netSel=document.getElementById('network'),layer=document.getElementById('routes');
const W=-70.752,E=-70.620,S=19.740,N=19.836;
const X=lon=>((lon-W)/(E-W))*880+10,Y=lat=>((N-lat)/(N-S))*590+10;
for(const c of r.competitors){const o=document.createElement('option');o.value=c.id;o.textContent=c.id+' · '+c.incremental_residents_vs_L1.toLocaleString('es-DO')+' habitantes nuevos';routeSel.appendChild(o)}
for(let i=0;i<r.network_combinations.length;i++){const c=r.network_combinations[i],o=document.createElement('option');o.value=i;o.textContent=c.routes.join(' + ')+' · '+c.incremental_residents.toLocaleString('es-DO')+' nuevos';netSel.appendChild(o)}
const number=x=>Number(x).toLocaleString('es-DO'), colors=['#f3cd65','#4bd2e6','#ff75a7','#90e584'];
function render(){
 const candidate=routeSel.value;
 const combo=r.network_combinations[Number(netSel.value)||0];
 const routes=new Set(combo?combo.routes:['L1',candidate]);routes.add(candidate);
 layer.replaceChildren();
 const create=(tag,attr)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attr))n.setAttribute(k,v);layer.appendChild(n);return n};
 for(let n=0;n<=8;n++)create('line',{x1:10+n*110,y1:10,x2:10+n*110,y2:600,stroke:'#31515e','stroke-width':1});
 for(let n=0;n<=6;n++)create('line',{x1:10,y1:10+n*98,x2:890,y2:10+n*98,stroke:'#31515e','stroke-width':1});
 let count=0;
 for(const f of feats){if(!routes.has(f.properties.id))continue;const pts=f.geometry.coordinates;
  for(let i=1;i<pts.length;i++)create('line',{x1:X(pts[i-1][0]),y1:Y(pts[i-1][1]),x2:X(pts[i][0]),y2:Y(pts[i][1]),stroke:colors[count%colors.length],'stroke-width':2,opacity:0.35});
  for(const p of pts)create('circle',{cx:X(p[0]),cy:Y(p[1]),r:3,fill:colors[count%colors.length]});count++;
 }
 const selected=r.competitors.find(z=>z.id===candidate);
 document.getElementById('summary').textContent=combo?'Combinación: '+number(combo.covered_residents)+' residentes próximos a paradas; +'+number(combo.incremental_residents)+' frente a L1; '+number(combo.covered_poi)+' POI.':'';
 document.getElementById('facts').textContent='L1: '+number(r.metadata.base_residents)+' residentes y '+number(r.metadata.base_poi)+' destinos | '+r.metadata.candidates+' competidoras generadas | '+r.metadata.pairs_attempted+' parejas exploradas. Esquema de paradas, no imagen satelital ni recorrido de calles.';
}
routeSel.addEventListener('change',render);netSel.addEventListener('change',render);
for(const c of r.competitors.filter(x=>x.id!=='L1').slice(0,12)){const tr=document.createElement('tr');for(const t of [c.id,number(c.incremental_residents_vs_L1),c.incremental_poi_vs_L1,c.round_trip_km]){const td=document.createElement('td');td.textContent=t;tr.append(td)}tr.onclick=()=>{routeSel.value=c.id;render()};document.getElementById('top').append(tr)}
render();
</script></body></html>'''
out.write_text(page.replace("__PAYLOAD__",payload),encoding="utf-8")
print("Offline comparator bytes",out.stat().st_size)
