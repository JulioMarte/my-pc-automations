# Matriz sintética de accesibilidad origen-destino por horario

Este módulo integra WorldPop 2025 (residencias estimadas), Overture Places (lugares y servicios) y las 22 paradas propuestas para L1. **No interpreta resultados como viajes realizados ni pasajeros previstos**. En ausencia de conteos de movilidad, todos los pesos por categoría y horario son hipotéticos.

Ejecución en CI: `synthetic-od`, posterior a generar `population.json`, `initial_route.geojson` y `destinations.geojson`. Resultado en `od_synthetic.json` con:
- resident_coverage_estimate: residentes modelados en 500 m de radio geométrico de la L1, contando cada celda una sola vez.
- origin_by_stop: residentes asignados a parada cercana.
- destinations_by_stop: puntos de interés por categoría y parada cercana.
- periods[].top_od_pairs: pares de paradas con puntuaciones sintéticas de oportunidades en 6 franjas.
  
La puntuación no tiene unidades de personas o viajes, y **no debe multiplicarse por tarifa para estimar ingresos**. Los horarios modelados son hipótesis y no reflejan conteos reales. La ruta L1 es provisional de ida, sus retornos y circulación de autobuses todavía no están validados. Este módulo no demuestra la complementariedad L1–L2 ni incorpora OpenTripPlanner/Valhalla.

Próximos trabajos imprescindibles:
1. Intersección y conectividad real con red peatonal mediante snapping a aristas, no radio euclidiano.
2. Geocodificación y deduplicación/verificación de puntos de interés y entradas públicas.
3. Matriz origen-destino observada y ponderaciones calibradas mediante encuestas, GPS y conteos.
4. GTFS con ida y vuelta **verificadas** y transbordos de L1 con L2/L3.
5. Evaluación integral tiempo puerta a puerta: caminata, espera, tiempo a bordo, transbordos, fiabilidad, y capacidad.
6. Optimización multiobjetivo con comparación frente a redes de referencia y tests de límites de giro/terminal.

El JSON no sustituye el estudio de ingeniería de movilidad ni define por sí solo ninguna ruta óptima.
