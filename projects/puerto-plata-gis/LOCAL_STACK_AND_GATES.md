# Motor local de planificación y contratos de aceptación

Este proyecto usa cálculos Python y archivos JSON/GeoJSON para un visor estático, sin un backend obligatorio.

**No inventar dimensiones del autobús.** Los valores `null` del vehículo son un bloqueo de validación real. Las pendientes y la sinuosidad generan penalizaciones graduales configurables, no rechazos automáticos. Se requieren datos del fabricante y reconocimiento de campo para aprobación de giros o terminales.

**Bibliotecas locales por función**: `pyvalhalla` (enrutamiento sobre tiles locales), `r5py` (matrices multimodales con Java 21 y GTFS), `osmnx` + `networkx` (grafos OSM), `geopandas` + `shapely` + `pyproj` (proyección EPSG:32619, geometrías), `rasterio` (DEM), `h3` (hubs), `ortools` (optimización exacta sobre coberturas discretas), `pandas` + `pyarrow` (tablas), `numpy` + `scipy` (estadística/índices), `Pillow` (tiles terreno). Instalar bibliotecas por etapa, no necesariamente todas para ver un HTML.

**Comparación de control**: ejecutar presupuestos de 10/20/30 buses con y sin obligación de L1; no afirmar ganador mientras no se incorporen costos de ciclo por corredor y cobertura de población por celda. La diferencia entre población cubierta y viajeros captados se debe mantener visible.

**Fases bloqueadas**: el éxito de GitHub Actions no convierte una fase en APROBADO. Cada fase requiere el entregable y las pruebas de aceptación. Valhalla local real, radios de giro, rutas continuas, GTFS fiable y aforos aún no están verificados.

Orden: (1) Valhalla/giros, (2) CRS y validadores, (3) búsqueda sin L1, (4) rangos OD calibrables, (5) OR-Tools presupuesto, (6) H3/GTFS/R5. Se pueden construir componentes auxiliares de fases posteriores, pero no declarar la fase cerrada antes de superar su gate.
