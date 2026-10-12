# Road Width Mapping — implementación incremental sin Ayuntamiento

## Estado

El CI del repositorio contiene un pipeline real de **inventario OSM** y
transectos de inspección a intervalos de 10 m, con salida JSON/GeoJSON.
No existe todavía ninguna ortofoto de Puerto Plata con resolución, cobertura,
licencia y georreferenciación verificadas que permita generar anchos observados.

No declaramos implementada la extracción satelital ni el barrido preciso del
Yutong. Datos OSM existentes no son medidas topográficas certificadas.

## Fuentes independientes

- [Geofabrik OSM](https://download.geofabrik.de/central-america/haiti-and-domrep.html): atributos voluntarios, no inventario de bordillos; ODbL.
- [IDERD](https://iderd.gob.do/recursos/directorio-de-geoservicios/): consultar WMS/WMTS/WFS y licencia de cada capa por separado. No se presupone ortofoto utilizable.
- [OpenAerialMap](https://openaerialmap.org/): comprobar cobertura, GSD, fecha, derechos y metadatos de cada imagen.
- [Mapillary](https://www.mapillary.com/): inspección visual de obstáculos y bordillos según condiciones de uso, no medición métrica directa.
- Sentinels 10 m/píxel: demasiado gruesos para márgenes de carril de un bus de 2.55 m.

No digitalizar imágenes de Google Maps, Esri ni proveedores comerciales sin licencia expresa de extracción de datos.

## Código incorporado

- `road_widths_pipeline.py`: inventaría tags OSM (width, est_width, lanes, maxwidth separados); ingiere muestras transversales CSV con origen y licencia; bloquea duplicados, errores geográficos y ausencia de incertidumbre en mediciones de campo; prohíbe certificar maniobras.
- `road_width_transects.py`: genera cortes sobre los ejes OSM cada 10 m. Son **zonas de inspección**, no anchos de calzada: el eje no determina bordillos. Equirectangular local para visualizar; no sirve para replanteo topográfico.
- `road_width_sources.json`: procedencia y licencias por verificar.
- CI `road-width-baseline`: descarga artefactos reales del grafo y publica inventario y transectos con controles explícitos.
- `turn_risk_screen.py`: cambios angulares de waypoints sin aprobación de giros.

## Ingesta de mediciones revisadas

Ejecutar desde `projects/puerto-plata-gis`:

```bash
python road_widths_pipeline.py --roads drive_network.geojson \
  --sources road_width_sources.json \
  --samples reviewed_width_samples.csv \
  --output road_width_baseline.json
```

CSV de entrada obligatorio:

```csv
segment_id,left_lon,left_lat,right_lon,right_lat,source,source_date,source_license,review_status,uncertainty_m
```

`review_status` en `unreviewed | visually_reviewed | field_measured`.
Debe declararse una licencia/permiso verificable por fuente y fecha de la
observación. El generador no asigna por sí mismo `accepted_for_bus=true`.

## Próximos gates

**G0 — Inventario**: grafo real OSM + proporción width conocido/desconocido,
transectos de búsqueda. Implementado, sujeto a CI.

**G1 — Imagen elegible**: ortofoto de ≤0.30 m GSD preferida, derechos de
extracción, datum, RPC/geotransform, control de error horizontal y fecha.
Sin imagen elegible: `BLOCKED_NO_LICENSED_GEOREFERENCED_IMAGERY`.

**G2 — Piloto**: revisar al menos 30 perfiles, comparar con medidas
independientes; criterio inicial error mediano ≤0.30m, al menos 90% ≤0.75m,
por ahora umbrales exploratorios no normativos.

**G3 — Automatización**: rasterio + segmentación/edición de bordillos,
perfil perpendicular en UTM19N, incertidumbre geográfica + de bordes
propagada, fotos antiguas/oclusiones marcadas UNKNOWN. Mantener revisión
manual con registro de cambios y de licencia.

**G4 — Intersecciones**: polígonos borde calzada, medianas, carriles,
obstáculos, estacionamiento temporal, desniveles; geometría de rodadura
real con plano de Yutong ZK6126HG y swept-path a varias velocidades.
Diámetro publicado ≤20.5m de variante kazaja no basta para certificar.

**G5 — Flota**: solo rutas con maniobras y ciclos calibrados pasan a CP-SAT
operativo. Curvas exploratorias 10/20/30 se conservan sin reinterpretar
como recomendaciones validadas.

## Limitaciones y salidas con evidencia

No obtener permisos municipales es compatible con G0-G3; G4 requiere
comprobación geométrica y campo, no necesariamente datos del Ayuntamiento.
Sin bordillos medidos, el resultado debe seguir siendo UNKNOWN. Ningún
CI verde debe confundirse con aprobación de rutas.

## Interfaz de revisión

Abrir `Road_Width_Review_Puerto_Plata.html` en un navegador con acceso a las bibliotecas públicas Leaflet.
Importar desde los artefactos CI `discovered_routes.geojson` y `priority_road_width_transects.geojson`.
La interfaz dibuja rutas en tres colores y líneas amarillas de inspección, con un límite visual de 7,000 para rendimiento.
**No digitalizar bordillos derivados de la capa satélite de referencia** sin permiso de extracción.

## Medición desde una máscara raster autorizada

Cuando exista una ortofoto georreferenciada con licencia que permita extracción de datos, es necesario generar/revisar una máscara binaria: **1=calzada, 0=fuera de calzada**. La herramienta NO segmenta automáticamente imágenes RGB ni identifica carriles, bordillos o medianas. Para medir ese límite de máscara:

```bash
python road_mask_measure.py --mask ./licensed_road_mask.tif \
  --transects road_width_transects.geojson \
  --catalog imagery_catalog.json --output measured_mask_widths.json
```

`imagery_catalog.json` deberá incluir exactamente un registro con `local_path` correspondiente a la máscara, `measurement_rights_confirmed:true`, `coverage_intersects_puerto_plata:true`, `georeferenced:true`, `crs`, `acquired_at`, `gsd_m <= 0.30` y `horizontal_accuracy_m <= 0.50`. La herramienta exige estos metadatos, verifica un CRS proyectado y genera SHA256 del raster. No sustituye una auditoría legal ni certificación independiente de exactitud. El resultado queda explícitamente marcado como estimación no verificada en campo.

## Primer resultado observado en CI

En la primera corrida válida del 12 de octubre de 2026 se inventariaron **8,096 aristas viales dirigidas** exportadas por OSMnx, incluyendo 430 registros con etiqueta `lanes`, **cero etiquetas `width`** en esa extracción, y **69,492 transectos de inspección**. Los 8,096 no representan necesariamente 8,096 calles distintas porque la red incorpora sentidos de circulación.

Ninguno de los transectos equivale a una medida; no existen aún imágenes registradas con licencia y precisión elegibles para el piloto, de modo que `imagery_eligibility_report.json` debe indicar bloqueo y `road_width_baseline.json` reportar cero observaciones.

## Cómo interpretar la nueva priorización

El trabajo `road-width-shortlist` filtra perfiles próximos a los **puntos provisionales** de C00-09, C00-10 y C02-04. No deduce el recorrido sobre cada calle entre paradas; esas geometrías son MultiPoint. Un perfil cercano a una parada es una prioridad de inspección, no un tramo de ruta confirmado.

## Resultado real del catálogo OpenAerialMap/HOT

El trabajo `imagery-catalog-discovery` consulta el endpoint STAC de HOT y
publica `open_aerial_metadata.json` con imagen, fechas, GSD, licencia
declarada, proveedor y procedencia. En la consulta inicial del 12 de octubre
de 2026 se observaron **14 registros**, pero solo **6 cajas delimitadoras
distintas**, fechados en septiembre de **2017**, resolución publicada
aproximada de **0.487 m/píxel**. Las seis zonas presentan metadatos
conflictivos de licencia (`CC-BY-4.0` frente a `CC-BY-NC-4.0`).
No cuentan con exactitud horizontal certificada en el inventario actual.

Por ello, **0 imágenes califican automáticamente** para medición de bordillos.
La resolución supera el umbral piloto de 0.30 m/píxel y la antigüedad es
importante en una ciudad donde cambian bordillos, estacionamientos y sentidos.
No confundir disponibilidad de metadatos con licencia o autorización para
crear una base de datos derivada ni con imágenes actualizadas.

## Cola de inspección de giros del Yutong

`survey_priority_queue.py` integra:
1. `yutong_turn_risk_screen.json` (ángulos estimados, no giros certificados).
2. `priority_road_width_transects.geojson` (puntos de inspección cercanos a paradas de las tres candidatas).

Salida `yutong_field_survey_queue.json`: tareas priorizadas por cambio angular, coordenadas del waypoint, perfiles vecinos a 90 m, referencia de vehículo y evidencia necesaria. No supone que una arista próxima sea parte efectiva de la ruta; los anchos y giros siguen `UNKNOWN`/`NOT_ASSESSED`.

La compilación del inventario OSM también retiene `est_width` y etiquetas de estacionamiento, antes descartadas. `width` (ancho anotado), `est_width` (estimación) y `maxwidth` (límite de paso de vehículo) nunca se intercambian; cuando falta la fuente primaria, el inventario informa la ausencia.

## Visor de las nueve inspecciones del Yutong

El visor `Road_Width_Review_Puerto_Plata.html` acepta ahora tres entradas opcionales: `discovered_routes.geojson`, `priority_road_width_transects.geojson` y `yutong_field_survey_queue.json`. Los puntos marcados se presentan como **giros candidatos pendientes**, sin afirmar que sus coordenadas coinciden con giros reales de calles. La capa Esri es solo para orientación visual, no una fuente autorizada de bordillos digitalizados.

## Captura manual desde el navegador (versión preliminar)

`Road_Width_Manual_Review.html` permite registrar puntos extremos de perfiles transversales visuales, identificador de tramo, fecha, fuente, declaración de licencia y una estimación de incertidumbre. Exporta un CSV con el mismo contrato que `road_widths_pipeline.py`, siempre con `review_status=unreviewed`.

**Importante:** colocar puntos con clics sobre OSM no constituye una medida métrica precisa del bordillo, porque el mapa base no es un levantamiento topográfico. El archivo debe contrastarse con ortofotos elegibles o coordenadas tomadas con medios adecuados. El CI valida la sintaxis JavaScript del visor y sus controles principales, pero no sustituye una prueba manual de navegador.

El visor `Road_Width_Review_Puerto_Plata.html` permite cargar además el archivo `yutong_field_survey_queue.json` de Actions para observar los 9 candidatos. El valor de diámetro publicado de otra variante Yutong continúa siendo una referencia exploratoria.

## Evaluación comparativa de imágenes para 9 giros (octubre 2026)

**Decisión ejecutada:** usar OpenAerialMap/HOT como catálogo abierto para
identificar evidencia visual histórica, **no** como fuente automática de ancho
de bordillos. Se incorporaron `audit_aerial_for_turns.py`,
`test_audit_aerial_for_turns.py` y el job `imagery-nine-turns-audit`.
Este análisis cruza los STAC bbox con los nueve puntos de la cola de
inspección y publica `image_turn_suitability.json` con bloqueadores
por imagen y giro. No usa imágenes restringidas ni supone que todo bbox
contiene píxeles válidos.

**Hallazgo comprobable:** cada uno de los nueve puntos aparece cubierto por
el bbox de dos registros STAC, uno CC-BY-4.0 y otro CC-BY-NC-4.0.
Eso significa **18 coincidencias de metadatos**, no 18 imágenes distintas
ni nueve giros medidos. Ambas series son de septiembre de 2017 y declaran
aproximadamente 0.487 m de GSD. El GSD es separación entre píxeles,
no exactitud horizontal; sin inspección de raster ni GCP, el margen real
de error de los bordillos no puede estimarse.

### Decisión por alternativa

- **OpenAerialMap 2017:** costo cero para catálogo y revisión visual,
  pero insuficiente para medir la envolvente del Yutong de forma confiable.
  Las imágenes CC-BY-NC requieren revisar restricciones adicionales si
  se busca uso comercial. Las de CC-BY también requieren atribución y
  verificar el archivo específico.
- **IDERD/IGN:** prioridad para explorar servicios geográficos nacionales
  con ortofotos disponibles y términos explícitos; no se afirma que ya
  existe una capa apta para Puerto Plata.
- **Pléiades Neo y WorldView:** 0.30 m GSD potencial en determinados
  productos, pero no equivalen a ±0.30 m de geolocalización; comprar
  solo para preseleccionar donde las fuentes gratuitas no sirvan.
- **Ortofoto aérea propia + puntos de control y mediciones terrestres:**
  mejor fuente para **los nueve giros realmente conflictivos**, cuando
  se cumplan permisos de vuelo y requisitos de seguridad y exactitud.
  Puede comenzar con medición directa desde tierra para evitar esperar
  un vuelo. Ninguna imagen sustituye el plano de barrido del vehículo.

**Criterio de aceptación:** resolver licencia por raster, comprobar
geotransformación, resolución, huella de píxeles válidos, fecha, precisión
horizontal mediante puntos de control y contraste independiente. Mientras
falte cualquiera de los controles decisivos, la salida es
`COVERAGE_SCREENED_NO_VALID_ROAD_WIDTH_IMAGERY`, nunca aprobación de giro.

## Reenfoque de ejecución sin presupuesto ni levantamiento (octubre 2026)

**Restricciones actuales:** no se dispone de recursos para comprar ortofotos,
contratar topografía, volar drones ni medir calles. Se evita planificar
estas acciones como prerrequisitos de los próximos entregables de software.
Se mantienen como bloqueos de validación física, documentados.

Se incorpora `zero_budget_roadmap.py`, probado e integrado a CI mediante
`zero-budget-evidence-roadmap`. Consume los artefactos reales
`road_width_baseline.json`, `image_turn_suitability.json` y
`yutong_field_survey_queue.json`; produce
`zero_budget_readiness.json` con decisiones y sus evidencias.

**Nuevo orden de trabajo ejecutable sin presupuesto:**

1. Completar metadatos OSM: sentidos, clasificación vial, carriles,
   `est_width`, `width`, superficie, estacionamiento y restricciones.
   Producir cobertura y huecos, sin inventar dimensiones.
2. **Reconstruir trazados reales de ida y vuelta por Valhalla**
   (polilíneas y aristas cuando la API las entregue), almacenar geometría
   con proveniencia. Los MultiPoint de paradas no constituyen calles recorridas.
3. Auditar restricciones legales y topológicas sobre el trazado real:
   sentidos prohibidos, retornos hipotéticos, carreteras estrechas sin
   medición, accesos, desvíos, continuidad y correspondencia con paradas.
4. Recalcular distancias, tiempos y sensibilidad 10/20/30 en el escenario
   no calibrado; separar velocidades/tiempos simulados de reales.
5. Examinar sensibilidad de demanda con WorldPop y escenarios OD sin
   presentar población cercana como pasajeros reales.
6. Mantener OpenAerialMap/IDERD como **catálogos de referencia**, buscar
   metadatos abiertos periódicamente, sin compra ni extracción automática
   de imágenes restringidas.
7. Continuar aplazados y bloqueados: simulación final de barrido, anchuras
   de bordillos, pasos críticos y homologación operativa.

**Regla obligatoria:** un dato desconocido es `UNKNOWN`, nunca
`PASS`; CI verde significa que el estudio se ejecutó correctamente,
no que una ruta fue aprobada para un Yutong de 12.17 m.

### Avance real de geometría por red abierta

Se añadió `valhalla_route_shape.py` al pipeline de Valhalla.
Decodifica las formas `trip.legs[].shape` que el motor entregue en
formato polyline6, y anota la salida `ROAD_GRAPH_SHAPE_NOT_SWEPT_PATH`.
En ausencia de un `shape` se escribe
`NO_SHAPE_IN_BACKEND_RESPONSE`, sin inventar trayectorias.
La geometría se incorpora en las evidencias de ida y vuelta en
`valhalla_local_audit.json`, junto con distancia y tiempo de red.
Pruebas unitarias sintéticas comprueban recuperación de coordenadas y
errores por geometría truncada.

La obtención de trazados de red **no valida** giros físicos ni
la altura, radio de giro o holgura lateral del Yutong.

## Geometría real y consistencia de paradas — siguiente fase sin presupuesto

La corrida de CI `38199157055` confirmó que Valhalla generó **19 recorridos candidatos (L1 + 18), todos con geometrías reales para ida y vuelta (38 polilíneas)**. El nuevo módulo `route_geometry_qa.py` exporta `routed_paths.geojson` y `routed_geometry_qa.json` con verificación por dirección; no aprueba espacio barrido ni retornos.

Se añade `route_waypoint_consistency.py` para comprobar proximidad entre los puntos MultiPoint candidatos y las líneas reales de Valhalla. La prueba es necesaria porque hasta aquí Valhalla une **terminales**, no obliga a pasar por cada parada. Las desviaciones >80 m se reportan en `route_waypoint_consistency.json` para revisión, no para afirmar imposibilidad operativa. Se debe recalcular la selección de rutas antes de convertir cobertura de paradas en recomendación.

Distancias observadas en la corrida CI: C00-09 (3.734 + 3.775 = 7.509 km), C00-10 (5.190 + 5.212 = 10.402 km), C02-04 (2.566 + 2.566 = 5.132 km). Son longitudes del camino elegido entre terminales, NO trayectos obligatoriamente visitando las paradas. Las distancias anteriores del optimizador permanecen exploratorias y no deben sustituirse sin consistencia de waypoints.

La nueva CI valida código, cobertura de geometrías y denuncia paradas desviadas; no tiene aforos reales ni validación geométrica del Yutong.

## Verificación de CI y nueva auditoría de waypoints

La ejecución `38199157055` quedó en verde en todos los 21 jobs,
con 19 recorridos de ida y vuelta (38 polilíneas). La ejecución
`38199624333` también confirmó 19/19 geometrías y reportó **9/19
candidatas con al menos un waypoint a >80 m** de las rutas calculadas
solamente entre terminales. En la selección de 10 autobuses,
`C00-09` tenía 0 puntos desviados, `C00-10` 9/20 y `C02-04` 6/12
en ambas direcciones según la métrica de distancia a polilínea.

**Corrección integrada:** `valhalla_waypoint_route.py` enruta cada par
consecutivo de puntos de las tres candidatas para generar un recorrido
que pase por esos anchors en el orden registrado. Exporta
`valhalla_waypoint_constrained.json` y
`valhalla_waypoint_constrained.geojson`. No fuerza aceptación de
todas las rutas: si falta un tramo o geometría, muestra BLOCKED con
evidencia. Las pruebas unitarias ejercitan éxito, fallo y puntos
duplicados. Ni el nuevo itinerario ni la distancia calculada sustituyen
la validación física de bordillos, terminales y espacio barrido.

**Implicación:** hasta comprobar esos itinerarios, el ranking exploratorio
de cobertura 10/20/30 no puede tratar los caminos directos de terminal
como rutas que realmente atienden todos los puntos GIS.
