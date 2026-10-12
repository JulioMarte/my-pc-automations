# Puerto Plata BRT — algoritmo V2 (sin rutas heredadas)

## Regla principal
**Nunca** alimentar generación, optimización, ranking o selección del V2 con L1,
C00-09, C00-10, C02-04 ni ninguna candidata del experimento anterior. Los
IDs `AUTO-xxx` se derivan del grafo OSM dirigido y las matrices OD sintéticas.
`historical_L1_control.json` se calcula únicamente DESPUÉS del ranking, no es
candidata ni semilla.

## Fuente y alcance
- `config.json`: único origen de todos los parámetros de escenario; el bbox
  **NO** es un perímetro urbano oficial, y no garantiza cubrir toda la ciudad.
- `zones_h3_res8.json`, `zones_h3_res9.json`: celdas H3 sobre el bbox;
  producción WorldPop 2025 estimada, atracción Overture por categoría configurable.
- `synthetic_gravity_od.json`: 3 escalas × 3 exponentes gravitacionales,
  normalizados por origen. Son unidades relativas, **no** pasajeros reales.
  Sosúa, Imbert y Santiago son puertas externas hipotéticas: volumen y punto
  de acceso supuestos. Si faltan aforos NO promover a observado.
- `desire_lines.geojson`, `top20_key_zones.geojson` y
  `map_desire_lines.html`: líneas rectas OD y celdas priorizadas,
  **no** trazados viarios.
- `generated_routes.geojson`: caminos OSM dirigidos por varios generadores;
  deduplicación de aristas. El objetivo 100–300 es un objetivo de diversidad;
  si no se logra, devolver insuficiencia, no rellenar artificialmente.
- `yutong_turn_screen.json`: variantes 20.5/21.5 m; Shapely proyecta
  huellas estáticas sobre eje cartografiado. No hay bordillos ni barrido
  cinemático continuo, así que **DUDOSO** y aprobación **0**.
- `scored_candidates.json`: paradas equidistantes con desplazamiento hacia
  H3 modelados, acceso OSM a pie (sin seguridad confirmada), OD direccional y
  penalización por caminata/espera. Suposición de retorno y tráfico explícita.
  `relative_od_per_bus` NO es pasajeros por autobús.
- `route_robustness.json`: 27 cruces de OD y velocidad, pero no calibra
  radios ni pesos perturbados ni capacidad; no se recomienda una línea.
- `networks_10_20_30.json`: OD única por máximo valor de contribución
  elegida mediante CP-SAT para 10/20/30, independiente y progresiva.
  Solo subconjunto prefiltrado de candidatas/OD. Puntaje matemático relativo.
  Conexiones con transbordo NO computadas todavía como viaje OD de dos tramos.
- `historical_L1_control.json`: evaluación A/B *después*, exclusivamente.
- `evidence_gates.json`: ocho pasos, incertidumbre, bloqueos y faltantes.

## Qué NO está completado
- Clasificación VIABLE/INVIABLE certificada a partir de huella barrida,
  datos de cunetas, radios, medianas y pendiente. Una etiqueta OSM de
  prohibición conocida puede eliminar un tramo; desconocimiento nunca implica
  que el bus cabe.
- Volumen observado y calibración de demanda, matriz OD real, pasajeros
  hora punta, cargas al 70–85 % de capacidad nominal.
- Tiempos reales por sentido/turno, fases semafóricas y tiempos de terminal.
- Transbordos peatonales seguros, cruce de aceras, accesibilidad universal,
  sincronización horaria, GTFS validado y análisis r5py puerta a puerta.
- Cobertura del perímetro urbano oficial fuera del bbox.
- Diseño físico de extensiones y gasto de infraestructura.

## Políticas de CI y reporte
1. Código válido + datos simulados reproducibles => **EXPLORATORIO**.
2. Falta dato crítico de geometría o seguridad => **BLOQUEADO**,
   nunca **APROBADO**.
3. `FEASIBLE_NOT_PROVEN_OPTIMAL` del solver nunca significa óptimo global.
4. Si falla o supera el tiempo, emitir **UNSOLVED**, no **INFEASIBLE**
   salvo certificado INFEASIBLE del solver.
5. No extrapolar matrices truncadas top-N como el total de viajes urbanos.
6. No mezclar modelos de rutas heredadas en informes del nuevo método.
7. El CI siempre debe publicar mapas, ranking, redes, procedencia, bloqueos
   e información crítica faltante; aun cuando no exista ruta aprobada.

Comandos de CI: job `algorithmic-v2-baseline` en
`.github/workflows/puerto-plata-gis.yml`.
