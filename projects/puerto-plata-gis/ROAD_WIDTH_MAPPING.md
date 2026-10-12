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
