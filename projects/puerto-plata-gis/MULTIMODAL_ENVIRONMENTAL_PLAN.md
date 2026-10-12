# Evaluación multimodal y ambiental — estado de integración

## Fuentes comprobadas / incorporadas
- **Valhalla**: motor de enrutamiento de código abierto; perfil `bus` respeta las restricciones cartografiadas en OSM cuando los datos existen. `valhalla_audit.py` puede llamar a un despliegue Valhalla mediante variable `VALHALLA_URL`, o el secreto de Actions `PUERTO_PLATA_VALHALLA_URL`. En ausencia de servicio, **solo exporta solicitudes pendientes y no valida ninguna ruta**.
- **NASA POWER**: `build_climate.py` obtiene climatología mensual de temperatura media, máxima, humedad relativa y precipitación para tres puntos de referencia del rectángulo urbano. NO informa temperatura de sombra/paradas ni calor real de una calle a una hora particular.
- **Tilezen / Mapzen Terrain Tiles**: `build_terrain.py` consulta elevaciones aproximadas en las 22 paradas de L1; NO mide inclinación de aceras, rampas ni accesibilidad universal.
- **OpenTripPlanner**: próximo motor a alimentar con OSM y GTFS **cuando se disponga de recorridos de ida/vuelta físicamente verificados**. La matriz OD sintética y el modelo de frecuencias que existen ahora NO sustituyen tiempos reales de viaje.
- **SUMO**: siguiente etapa para inspección de maniobrabilidad y ciclos, requiere validación explícita de carriles e intersecciones locales.

## Insumos críticos de la optimización posterior
1. Para cada par origen-destino, tiempo a pie real, longitud, pendiente, sombra, seguridad vial y condiciones de calor/lluvia por período.
2. Demanda real por origen, destino, horario y sentido: contar pasajeros/encuestas de viajes; no inferir viajes directamente de la población WorldPop o la cantidad de negocios.
3. Recorrido de bus continuo, restricciones de giro OSM y validación de radio de giro/terminal para largo/ancho específicos de cada vehículo.
4. Una red de líneas coordinada: tiempo de transbordo, horario y confiabilidad, tarifa integrada, frecuencia meta de 10 minutos (meta de paso, no espera máxima garantizada).
5. Función multiobjetivo y métricas de Pareto: tiempos medios y percentil 90 de viaje, población y destinos alcanzables en 30/45 min, costo vehicular, coste horario, kilómetros, emisiones y equidad territorial.

## Importante: interpretación de L1 y otras rutas
Un alto número de residentes a 500 m de una parada **no demuestra** acceso efectivo entre zonas residenciales, ni que L1 sea el mejor corredor inicial. Tampoco el algoritmo OSMnx garantiza pasos correctos en Luis Ginebra, rotondas u otras avenidas divididas.

## Ejecutar localmente
```bash
python build_terrain.py
python build_climate.py
python valhalla_audit.py
# Para ejecutar contra Valhalla ya desplegado:
VALHALLA_URL=http://localhost:8002 python valhalla_audit.py
```

Antes de publicar cifras, verificar los artefactos generados, la versión de datos y la consistencia de la geometría. Las lecturas ambientales son insumos externos separados; no cambian aún el ranking de corredores.
