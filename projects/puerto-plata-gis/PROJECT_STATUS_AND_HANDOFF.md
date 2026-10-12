# Estado verificado y handoff técnico — Puerto Plata GIS

**Corte de auditoría:** 11 de octubre de 2026, rama `feat/puerto-plata-transit-gis` (verificar HEAD antes de continuar).
**Fuente de verificación:** GitHub Actions GIS run [38192644466](https://github.com/JulioMarte/my-pc-automations/actions/runs/38192644466), 15 jobs concluidos `success`. **El estado verde solo significa ejecución de los jobs; no significa validación técnica del trazado ni aprobación de las fases.**

## Contexto y objetivo

L1 provisional UASD → Av. Manolo Tavárez Justo → Oasis → Playa Dorada. Comparar tanto **red con L1 obligatoria** como **control sin L1 obligatoria**, con zonas residenciales y destinos accesibles a pie y por tránsito. Optimizar progresivamente tiempos de viaje, cobertura equitativa, costo y cantidad de autobuses. No afirmar superioridad definitiva de L1 hasta ejecutar modelos multimodales y obtener demanda calibrada.

## Hallazgos recientes que no deben perderse

### Valhalla: ruta real BLOQUEADA CON EVIDENCIA

- Job `real-local-valhalla` **terminó verde**, pero el script informó `BLOCKED_WITH_EVIDENCE`. Error concreto registrado: `[Errno 2] No such file or directory: '/tmp/pp-valhalla/results/valhalla_tiles.tar'`. `routed_both_directions` fue `null`: **NO se comprobaron giros ni regresos reales** en esa ejecución.
- Otro job, `valhalla-local-real-tiles`, terminó verde y publicó artefacto `puerto-plata-valhalla-rutas-locales`; hay que leer ese artefacto, no extrapolar el éxito de un job a la validación física.
- `build_valhalla_local_tiles.py` y `run_local_valhalla_evidence.py` usan rutas de generación/extracción diferentes; **primero reconciliar configuración, ubicación de tiles y forma de pasar los archivos al Actor**. Añadir prueba end-to-end del archivo generado, sin borrar evidencia negativa.
- `valhalla_local.py` utiliza `Actor` local. Incluso cuando devuelva rutas en ambos sentidos, siguen faltando: continuidad de giro en terminal, barrido de carrocería, apertura de mediana, espacio en carril y comprobación de campo (especialmente Luis Ginebra).
- Entregable pendiente: auditoría **por maniobra** con `candidate,lat,lon,vehicle,status,reason,source`, clasificación `DESCARTAR/CORREGIR/REVISAR_EN_CAMPO`. No fabricar geolocalizaciones de giros.

### Curva 10/20/30: EJECUTADA, EXPLORATORIA

Job `exploratory-fleet-curve` verde, artefacto `puerto-plata-curva-flota-exploratoria`. `run_exploratory_curve.py` usó velocidades medias supuestas de 12, 18 y 24 km/h y pausa terminal supuesta de 12 min. La vuelta de L1 se aproxima como **2 veces la longitud de ida**: esto **no** valida el retorno. Población WorldPop estimada cubierta por paradas; **no son abordajes reales**.

| Velocidad hipotética | Flota | Con L1 obligatoria | Sin L1 obligatoria |
|---|---:|---:|---:|
| 12 km/h | 10 | 25,933.44 | 30,477.05 |
| 12 km/h | 20 | 40,207.04 | 40,207.04 |
| 12 km/h | 30 | 45,680.64 | 45,680.64 |
| 18 km/h | 10 | 29,327.44 | 32,767.31 |
| 18 km/h | 20 | 42,126.99 | 42,126.99 |
| 18 km/h | 30 | 47,214.09 | 47,214.09 |
| 24 km/h | 10 | 29,327.44 | 36,216.49 |
| 24 km/h | 20 | 44,075.88 | 44,075.88 |
| 24 km/h | 30 | 48,476.20 | 48,476.20 |

Estos resultados resuelven **un problema matemático condicionado a supuestos ficticios**, no un plan de transporte. Para flota 10, el escenario libre supera la cobertura obligando L1 bajo las tres velocidades supuestas; esto **es una señal para investigar, no una prueba de que L1 sea mala**. Para otros presupuestos pueden coincidir por las restricciones/objetivo. La función objetivo maximiza residentes próximos a paradas, no la utilidad de viajes ni la frecuencia óptima según demanda.

### Vehículo definido solo como referencia

`study_config.json`: Mercedes-Benz **Citaro K**, longitud 10.633 m, ancho 2.55 m (espejos 2.95 m), círculo de giro 17.284 m. Fuente: fabricante, enlazada en configuración. La mitad del diámetro **no es el radio barrido**. `maximum_grade_percent:null`, capacidad de variante `null`, `datasheet_verified:false`; NO completar con suposiciones. Vehículo no seleccionado para compra ni aprobado para operación local.

### Cobertura y demanda

- L1: unos 19,046 residentes estimados en radio de caminata **por red OSM** de 500 m y tolerancia de conexión de 60 m; antes 19,707 con 120 m. Radio euclidiano 500 m daba 41,114: **tres métodos distintos**, no cifras intercambiables. No son pasajeros.
- Hay corredores provisionales C00-10, C02-04 etc. generados desde grafo OSMnx; ninguno tiene giro/terminal certificado.
- `build_od_synthetic.py` produce seis períodos de **oportunidades sintéticas**, no una OD observada. La captura 2/5/10 % del archivo de configuración son sensibilidades hipotéticas, no pronósticos.
- `AFOROS_Y_CALIBRACION.md` y `PLAN_AFOROS_Y_FUENTES.md` identifican documentos/solicitudes INTRANT y Ayuntamiento y proponen 3–4 puntos de observación. **No hay aforos verificados importados**, y no debe decirse que está calibrada la demanda.
- `r5_accessibility.py` y tests de `r5py`/Java 21 existen, pero **no hay matriz real multimodal** sin PBF y GTFS de rutas completas.

### Componentes y fuente de verdad

| Necesidad | Archivo principal | Estado |
|---|---|---|
| Configuración/supuestos | `study_config.json` | Presente; ficha parcialmente verificada |
| Acceso peatonal por red | `network_access.py` | Ejecutado, limitaciones por aceras/cruces |
| Competidoras y unión | `discover_transit_network.py` | Ejecutado, geom. de bus no aprobada |
| Valhalla local | `run_local_valhalla_evidence.py`, `valhalla_local.py` | Bloqueo real en una ejecución; auditar ambos artefactos |
| CRS y geometrías | `validate_spatial.py` | Validador creado, EPSG:32619 de referencia |
| Flota por frecuencia | `optimize_headways.py`, `prepare_optimization_input.py` | Lógica con/sin L1 y 10/15/20; exige ciclos |
| Curva exploratoria | `run_exploratory_curve.py` | Ejecutada, no calibrada |
| Aforos | `audit_counts.py` | Importador, sin base observada |
| Matriz OD | `build_od_synthetic.py` | Sintética |
| Puerta a puerta | `r5_accessibility.py` | Motor instalado, sin cálculo real de red |
| Gates | `phase_gates.py` | Bloquea sin revisión independiente, revisar enforcement |
| Visor | `index.html`, `render_route_competition.py` | Disponible, algunas vistas aún esquemáticas |

## Librerías locales

Preferir herramientas locales: `pyvalhalla`, `r5py` + **Java 21**, `osmnx`, `networkx`, `geopandas`, `shapely`, `pyproj`, `rasterio`, `h3`, `ortools`, `numpy`, `scipy`, `pandas`, `pyarrow`. **No todas están operativas dentro del pipeline**: H3 y cálculo real de tránsito GTFS/R5 todavía faltan. Evitar mantener servidores HTTP si basta biblioteca local.

## Contratos de aceptación y prioridades

**Ninguna fase 0–9 aprobada integralmente.** El gate debe requerir requisitos + revisión explícita de artefacto y responsable; no inferir aprobación de un archivo JSON creado o job verde.

1. Corregir falla de Valhalla real y **repetir ejecución hasta obtener evidencia de rutas o fallo técnicamente identificado**, no un falso éxito. Revisar contenido del artifact y SHA de PBF/tiles.
2. Inspeccionar maniobras y retornos por vehículo (Luis Ginebra, enlaces terminales); distinguir motor OSM de barrido físico de autobús.
3. Calcular ciclos y flota 10/15/20 con fuente `measured`, `calibrated_simulation` o `uncalibrated_simulation`, y comparar 10/20/30 buses con/sin L1. No vender la curva exploratoria como recomendación.
4. Obtener aforos INTRANT/Ayuntamiento/operadores o hacer observaciones seguras en 3–4 puntos, varias fechas/sentidos/horas; medir errores e incertidumbre. Nunca convertir porcentajes ilustrativos en previsiones.
5. Consolidar EPSG:32619 y DEM por arista; H3/GTFS/r5py para viajes puerta a puerta; función de elección que evalúe tiempos, equidad, cambios de línea y costos, no solo proximidad.
6. Actualizar visor sencillo con los resultados **reales** y un panel de bloqueos, fuentes y sensibilidad.

## Reglas para entregar al usuario

Informar en español commit, branch, modificaciones, job, resultados y bloqueos con enlace. Si algo está `BLOCKED_WITH_EVIDENCE`, describir su causa aunque el CI sea verde. No prometer progreso asíncrono. No efectuar `merge` a `main` sin instrucción explícita.
