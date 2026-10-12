# Auditoría de vehículo, giros, flota y aforos

## Vehículo de referencia: Mercedes-Benz Citaro K
Fuente primaria: https://www.mercedes-benz-bus.com/es/es/models/citaro/facts-citaro.html

| Magnitud | Valor | Estado |
|---|---:|---|
| Longitud | 10.633 m | Ficha del fabricante |
| Anchura carrocería | 2.550 m | Ficha del fabricante |
| Anchura con espejos | 2.950 m | Ficha del fabricante |
| Diámetro del círculo de giro | 17.284 m | Ficha del fabricante |
| Medio diámetro (valor geométrico derivado) | 8.642 m | Derivado, **no** radio barrido |
| Pendiente máxima admisible con carga | Desconocida | BLOQUEADO |
| Capacidad de pasajeros de variante específica | Desconocida | BLOQUEADO |
| Variación de ejes/voladizos y anillo barrido | Disponible parcialmente en ficha | No simulado |

Este vehículo es una referencia para evaluar el caso de un autobús urbano compacto, **no una selección comercial ni una aprobación de circulación local**. La ficha especifica un círculo de giro pero no permite concluir automáticamente que una intersección tenga suficiente radio libre. Se requieren acceso al carril, apertura de mediana, barrido de cola y espejos, radios efectivos, maniobras de terminal y obstáculos.

## Pipeline aplicado

1. `build_valhalla_local_tiles.py`: preparar tiles desde PBF OSM (requiere build local de pyvalhalla). Publica SHA-256 de entradas y salida.
2. `valhalla_local.py`: comprobar A→B y B→A para candidatos, siempre `bus_geometry_validated:false`; no hace aún simulación de barrido de trayectoria.
3. `prepare_optimization_input.py`: proyectar paradas y población sobre grafo peatonal, calcular cobertura por celda única y exigir CSV con tiempo de ciclo/procedencia. Sin tiempo de ciclo, el paso se bloquea.
4. `optimize_headways.py`: optimizar cobertura sin doble conteo para 10/20/30 buses, 10/15/20 minutos de intervalo, con y sin L1 obligatoria. Validez operacional de los insumos es una condición obligatoria, excepto modo `--exploratory`.
5. `audit_counts.py`: importar aforos observados con fecha/período, procedencia y duración; rechazar conteos sin evidencia.

## CSV de ciclos — contrato, no cifras inventadas

Cabecera: `route_id,cycle_minutes,cycle_source,operational_geometry_approved`

Valores permitidos de `cycle_source`: `measured`, `calibrated_simulation`, `uncalibrated_simulation`. Si el dato es una simulación no calibrada, el cálculo puede funcionar en modo exploratorio pero **nunca** es una flota operativa aprobada.

## CSV de aforos — contrato

Cabecera: `count_point,route_id,period,boardings,observation_minutes,source`

Fuente debe identificar encuesta/conteo real; se informa una tasa horaria normalizada **no** una predicción de demanda regional.

## Orden para cerrar gates

- Primero comprobar que el local Valhalla produce ambos sentidos y que la conexión entre el fin de ida e inicio de vuelta es físicamente posible. Para Luis Ginebra, revisar las medianas en imágenes de alta resolución y con levantamiento de campo.
- Segundo calcular ciclos propios de cada candidata para el vehículo elegido, incluyendo pausas y condiciones de circulación. No convertir un tiempo de carretera sin paradas en un ciclo comercial.
- Tercero completar aforos observados, rangos y validación de demanda OD, antes de inferir abordajes.
- Cuarto ejecutar CP-SAT sobre presupuestos, más r5py/GTFS para tiempos puerta a puerta. Una red que cubre más residentes pero no mejora viajes puede perder en el criterio multicriterio.

**El estado APROBADO de un CI solo confirma pruebas del código, nunca ingeniería de rutas o aceptación municipal.**
