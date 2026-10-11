# Puerto Plata Línea 1 — Laboratorio GIS

Aplicación web independiente dentro de `my-pc-automations`. Mapa satelital Esri, calles y rótulos OpenStreetMap/CARTO, paradas editables y cobertura ajustable. Por defecto se usa **500 m de radio (1,000 m de diámetro)**.

## Datos demográficos

`population.json` se genera automáticamente en CI a partir de **WorldPop constrained 2025 R2025A alpha** (celdas ~100 m). Son estimaciones de población, NO los conteos del Censo ONE 2022 a nivel de manzana. ONE 2022 se cita como referencia y necesita una cartografía homologable antes de usarlo en análisis por tramo.

Fuente: https://hub.worldpop.org/geodata/summary?id=73215 (datos CC BY 4.0 con posibles derivados ODbL). La cifra de cobertura suma una sola vez las celdas cuyo centro cae dentro de al menos un círculo alrededor de parada. No modela la red caminable ni cuantifica demanda real.

## Acceso y despliegue

Descargar el artefacto **puerto-plata-gis-completo** desde Actions. Extraer y ejecutar servidor estático desde la carpeta del HTML: `python -m http.server 8000`, visitar localhost:8000. No abrir HTML como `file://`: los navegadores restringen `fetch` de `population.json` local. El HTML sin el JSON de población sigue mostrando los mapas base y herramientas, pero no ofrece estimación demográfica.

## Límites

- El trazado UASD–Oasis aún no está digitalizado oficialmente; se dibuja manualmente o importa en GeoJSON y no se afirma que una línea recta sea una ruta real.
- WorldPop 2025 es dato modelado experimental: hay incertidumbre por celda, no se ha cotejado con ONE submunicipal.
- La cobertura por radio euclidiano no equivale a distancia peatonal.
- El sitio necesita internet para tiles y librería Leaflet.
- Esta rama está aislada y no altera otros servicios del repositorio.

## Evaluación actualizada

Radio predeterminado: **500 m**, editable entre 100 y 1,200 m. La suma basada en centros de celdas WorldPop de las 22 paradas provisionales aumenta aproximadamente de 17,148 a **41,114 residentes modelados** al cambiar de 250 a 500 m de radio. No es población censal ONE ni cantidad de pasajeros. Las calles de un solo sentido y los anchos de calzada no se validan automáticamente; hay que corroborar con OSM por tramo y trabajo de campo. Los nombres de comercios del panel están respaldados por fuentes, pero no se colocan pines con coordenadas no confirmadas. La acción de 'sugerir mejora' ordena las paradas por aporte residencial exclusivo, sin generar rutas viales ficticias.
