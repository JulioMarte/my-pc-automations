# Evaluación de redes con acceso peatonal por calles

## Implementado

- `network_access.py` utiliza grafo peatonal OSMnx dirigido, índice espacial STRtree, proyección de paradas y celdas de población sobre segmentos y Dijkstra. Devuelve cobertura a 500 m y estadísticas separadas dentro/fuera del recorte vial.
- `--sensitivity` recalcula 30, 60 y 120 m de tolerancia de conexión y permite observar cuánto depende la estimación de esta hipótesis. Esto **no sustituye validación de aceras, cruces ni barreras**.
- `compare_network_scenarios.py` recibe una lista de escenarios con varias líneas y evalúa la **unión** de las paradas en cada uno. Compara tanto residentes WorldPop como registros de POI alcanzables a pie, y calcula diferencia contra el primer escenario. Al sumar las paradas en un solo cálculo no suma dos veces la población entre L1, L2 y L3.
- La configuración predeterminada es solo L1. Los candidatos previos 54, 23 y 21 quedan **sin aprobación**: los giros de retorno no fueron validados y no se deben vender como rutas factibles.

## Ejecución

```bash
python network_access.py --graph walk.graphml --population population.json --route initial_route.geojson --sensitivity
python compare_network_scenarios.py --graph walk.graphml --population population.json --destinations destinations.geojson --baseline initial_route.geojson
python -m unittest -v test_network_access.py test_network_scenarios.py
```

Ejemplo de configuración externa `scenarios.json` (coordenadas **meramente ilustrativas**, reemplazar por paradas estudiadas y verificadas):

```json
{
  "scenarios": [
    {"name":"Base L1","routes":[{"id":"L1","bus_geometry_validated":false,"stops":[[19.8,-70.7],[19.79,-70.69]]}]},
    {"name":"Base + alternativa","routes":[{"id":"L1","bus_geometry_validated":false,"stops":[[19.8,-70.7],[19.79,-70.69]]},
      {"id":"CANDIDATA","bus_geometry_validated":false,"stops":[[19.8,-70.68],[19.79,-70.67]]}]}
  ]
}
```

Usar `python compare_network_scenarios.py --scenario-config scenarios.json` solo después de preparar ubicaciones geográficas; este ejemplo no corresponde a recorridos aprobados. El atributo `bus_geometry_validated` es una declaración del operador, **no lo valida el algoritmo**.

## Pendientes imprescindibles

1. La red peatonal OSM no garantiza aceras transitables, pasos seguros ni barreras físicas. Especialmente en avenidas con separador, la cartografía puede permitir cruces que no existen.
2. Solo se usa el **segmento cartográfico dirigido más cercano** como candidato de conexión: en calzadas paralelas o cruces cercanos puede atribuir el lado equivocado.
3. Una parada provisional puede ser inadecuada para colocar un autobús.
4. El comparador mide **acceso cercano a paradas**, no viaje puerta a puerta hasta destinos: no incorpora horarios, transbordos, congestión, tarifa, capacidad ni giros.
5. POI puede incluir duplicados y establecimientos desactualizados.
6. WorldPop produce residentes estimados, no viajes. Falta matriz origen-destino observada y modelar horarios y sentidos de la demanda.

No seleccionar ni financiar rutas por estos resultados sin los puntos anteriores.
