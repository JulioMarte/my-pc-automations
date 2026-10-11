# Inventario de destinos y análisis preliminar de rutas (2026-10-11)

## Fuente POI
Overture Maps Places descargado por `build_destinations.py` dentro de BBOX WGS84 -70.752,19.740,-70.620,19.836. Reporte de ejecución: 783 registros clasificados: retail 352, health 75, education 44, recreation 93, lodging 141, transport 39, jobs 39.

**Advertencias de calidad:** la extracción clasifica por texto de `basic_category`, de modo que algunas categorías son muy amplias. Se observaron 65 coordenadas duplicadas, nombres de destinos posiblemente mal localizados (por ejemplo referencias a otros municipios), hoteles mal clasificados y hospitales clasificados como oficinas. El inventario NO son 783 puntos independientes confirmados y NO es dato de demanda o empleo. No multiplicar cualquier peso de categoría para inferir viajes efectivos.

Google Places no es la fuente persistente principal por sus términos de almacenamiento/reutilización. Overture publica datos con licencias permisivas (aplican atribuciones y condiciones por procedencia).

## Intersección geométrica de los POIs con L1
Usando círculos de 500m alrededor de las 22 paradas OSRM provisionales:
- 41,114 residentes WorldPop 2025 modelados.
- 291 registros POI dentro de los círculos. Esta métrica es distancia en línea recta, NO acceso caminable ni verificación de entrada peatonal.

## Dos trazados exploratorios sobre el grafo DRIVE dirigido
Se usan rutas más cortas NetworkX entre **anclas aproximadas**, no una optimización multiobjetivo de corredores. Se simulan paradas cada 500m sobre la secuencia de nodos y se suman celdas WorldPop dentro de 500m euclidianos. Los datos son un indicador de oportunidad, NO vías confirmadas para buses.

| Corredor / sentido | km de nodos | Población geométrica del sentido | Población adicional a L1 | POI adicionales a L1 |
|---|---:|---:|---:|---:|
| San Marcos–Padre Granero (ida) | 4.64 | 26,391 | 3,815 | 15 |
| San Marcos–Padre Granero (vuelta) | 4.69 | 26,419 | 4,115 | 16 |
| La Sirena–Torre Alta (ida) | 2.78 | 14,914 | 5,243 | 105 |
| La Sirena–Torre Alta (vuelta) | 2.42 | 12,208 | 6,434 | 115 |

**No sumar ida y vuelta:** se superponen. No comparar cifras de destinos brutos sin depuración. Distancias aproximadas desde nodos y caminos mínimos, no distancias de calzada auditadas. La ancla de Padre Granero es una ubicación aproximada no verificada; el punto de San Marcos procede de un negocio que no necesariamente representa el centro del barrio.

## Decisión
Los resultados hacen **prometedora la exploración de La Sirena–Torre Alta**, pero NO justifican descartar San Marcos–Padre Granero ni modificar L1. Las rutas están altamente determinadas por las anclas y no incluyen matriz de demanda origen-destino, tiempos reales, transbordos, aceras ni admisibilidad para autobuses.

Siguientes controles antes de rediseñar:
1. Depurar POI duplicados y validar hospitales, escuelas, terminales, comercios y destinos recreativos prioritarios.
2. Añadir equipamientos OSM y, si están disponibles, catálogos ONE/ministerios con geometría.
3. Proyectar paradas y población a aristas peatonales, no al nodo más próximo; calcular isócronas caminables 500m.
4. Calcular rutas de ida/vuelta completas con filtros de bus y comprobar anchuras, radios de giro, desniveles y restricciones.
5. Estimar demanda O-D, viajes por franja y accesibilidad incremental por sector; optimizar pasajeros potenciales por vehículo-hora, no solamente población cercana.
