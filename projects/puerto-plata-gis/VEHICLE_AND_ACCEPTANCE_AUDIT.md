# Auditoría de vehículo, giros, flota y aforos

## Vehículo principal del estudio: Yutong ZK6126HG (urbano diésel Euro V)

Selección explícita del proyecto. Esta selección **no** significa homologación de rutas, aprobación de compra ni certificación de maniobras.

Fuente primaria: https://en.yutong.com/products/ZK6126HG.shtml

| Magnitud | Valor | Evidencia |
|---|---:|---|
| Largo | 12.170 m | Ficha Yutong |
| Ancho carrocería | 2.550 m | Ficha Yutong |
| Alto | 3.180 m | Ficha Yutong |
| Asientos | 36 pasajeros + conductor | Ficha Yutong |
| Capacidad anunciada | 90 o 95 pasajeros según configuración | Ficha Yutong; 100 según variante Kazajistán |
| Emisiones | Euro V | Ficha Yutong |
| Suspensión | Neumática | Ficha Yutong |
| Ángulos de ataque y salida | 8° / 8° | Ficha Yutong |
| Batalla / distancia entre ejes | Pendiente de confirmar versión | No certificar 6 m sin plano de chasis |
| Anchura con espejos | Desconocida | Pendiente |
| Diámetro mínimo de giro, variante Yutong Kazajistán | ≤20.5 m | Fuente oficial; referencia, no certificado para unidad elegida |\n| Espacio barrido con espejos | Desconocido | BLOQUEADO para aprobación física |
| Pendiente máxima cargado | Desconocida | BLOQUEADO |
| Puertas, rampa, transmisión, frenos y anticorrosión exactos | Dependen de oferta/configuración | Pendiente de fabricante |

**Regla del cálculo:** los campos geométricos no publicados siguen como null. No trasladar al Yutong el círculo de giro de 17.284 m del Citaro K. Tampoco afirmar que una ruta de OSM o Valhalla es maniobrable solo porque conecta los extremos. Para cada giro y retorno se necesitará geometría del espacio barrido, apertura libre de mediana, espejos, voladizos, ángulos de aproximación, obstáculos, pendiente y margen de seguridad.

**Capacidad:** registrar variantes [90, 95, 100], y para estimaciones preliminares usar 90 como extremo inferior anunciado. Es un supuesto de vehículo, **no** un aforo observado ni significa que sea legal operar siempre a plena capacidad.

**Historia de modelos:** el Mercedes-Benz Citaro K (10.633 m) queda como referencia histórica de escenarios previos, NO como vehículo seleccionado. Los resultados anteriores 10/20/30 dependen de ciclos hipotéticos y deben recalcularse/verificarse con la geometría del Yutong antes de aprobación.

**Solicitud imprescindible al fabricante:** plano acotado de la variante ofertada (incluyendo espejos y voladizos), curva de barrido/radio mínimo de giro a distintas velocidades y con carga, batalla, masas por eje, despeje al suelo, pendiente máxima arrancando con plena carga, accesibilidad/rampa y homologación de la configuración concreta.

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

## Actualización: referencia de giro de fábrica

Yutong Kazajistán publica **diámetro mínimo de giro ≤20.5 m** y batalla de 6.0 m; fuente: https://www.yutong.com.kz/products/ZK6126HG-param.shtml. La misma ficha incluye altura de 3.35 o 3.39 m y capacidad de hasta 100 pasajeros según configuración, distintas de otras versiones. No mezclar estas cifras como si fueran la misma unidad. Para sensibilidad se estudian diámetros 20.5 / 21 / 21.5 m, sin equipararlos al barrido total ni certificar retornos. Los escenarios 10/20/30 siguen siendo exploratorios hasta conseguir dimensión de espejos, barrido y anchos libres por cruce.
