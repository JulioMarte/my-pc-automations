# r5py local: matrices de accesibilidad Puerto Plata

El módulo `r5_accessibility.py` procesa viajes en Python usando R5, **sin servicio HTTP**, y produce `r5_accessibility.json`.

## Dependencias y datos

```bash
python -m pip install "r5py>=1.1.0,<2"
# Instalar también una versión de Java compatible según la documentación vigente de r5py.
```

Requiere **un extracto OSM .osm.pbf**, diferente de los `drive.graphml` y `walk.graphml` actuales. Sin GTFS solo puede calcular modos de red de calles, por ejemplo caminata. Para analizar la red propuesta de autobuses necesita uno o más archivos GTFS **válidos para la fecha consultada**, con recorridos de ida y vuelta comprobados.

```bash
python r5_accessibility.py --osm-pbf ./data/dominican-republic-latest.osm.pbf \
  --population population.json --destinations destinations.geojson \
  --departure 2026-10-14T08:00:00 \
  --max-origins 80 --max-destinations 80 --output r5_walk.json

python r5_accessibility.py --osm-pbf ./data/dominican-republic-latest.osm.pbf \
  --gtfs ./data/puerto-plata-propuesta.gtfs.zip \
  --departure 2026-10-14T08:00:00 --output r5_transit.json
```

El script **no genera ni verifica GTFS** ni descarga PBF, y tampoco infiere demanda observada. La muestra actual toma las 80 celdas de población más altas y los primeros 80 POI; **no es representativa** para declarar porcentajes válidos a escala municipal. El porcentaje reportado solo se refiere a la población de orígenes muestreados y a llegar al menos a uno de los destinos muestreados. Un estudio final debe emplear muestreo espacial equilibrado o cobertura completa, con pesos adecuados.

El resultado contiene tiempos por par `from_id`, `to_id`, `travel_time` y población de origen con al menos un destino accesible en 15, 30 o 45 minutos. Para comparar redes, utilizar **exactamente los mismos orígenes, destinos, fecha y métricas**, cambiando el GTFS de cada escenario. Sin GTFS, el modo de caminata ofrece una referencia independiente de las rutas de bus.

## Estado de verificación

Las pruebas `test_r5_accessibility.py` se ejecutan en CI sin datos externos. Una prueba de instalación importa la API de la versión compatible. **Todavía no es una prueba end-to-end de una red R5 de Puerto Plata**: faltan PBF y GTFS validados para realizar el cálculo real. El éxito de CI prueba la aritmética y el adaptador, no la calidad de una ruta.
