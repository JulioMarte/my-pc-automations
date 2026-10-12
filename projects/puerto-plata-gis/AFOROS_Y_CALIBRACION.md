# Aforos y calibración — Puerto Plata (fuentes verificables, sin valores inventados)

**Estado:** NO CALIBRADO. Ningún documento localizado en esta auditoría se ha importado como una matriz origen-destino completa, y la cuota modal no equivale a demanda de abordajes de L1.

## Documentos oficiales para solicitar datos originales

1. Ayuntamiento: presentación del *Plan de Movilidad Vial Urbana* elaborado por INTRANT (5 junio 2025). Señala conflictos en Av. Manolo Tavárez Justo, Av. Caamaño y Penetración al Muelle. Solicitar al INTRANT **tablas de aforos por sentido, hora, tipo de vehículo, intersección, estudio de velocidad y matrices OD**.
   https://ayuntamientopuertoplata.gob.do/alcalde-roquelito-participa-en-presentacion-del-plan-de-movilidad-vial-de-puerto-plata/
2. Diagnóstico municipal con encuestas de modos de transporte y caracterización por distrito. La cuota modal NO es tasa de captura para líneas nuevas. Solicitar ficha de muestreo, microdatos anonimizados, zonas y fechas.
   https://ayuntamientopuertoplata.gob.do/transparencia/wp-content/uploads/2026/04/01-DIAGNOSTICO.pdf
3. Formulación territorial del municipio (objetivo de movilidad y capas Arup 2025). Solicitar shapefiles/cartografía de terminales, vías y nodos.
   https://ayuntamientopuertoplata.gob.do/transparencia/wp-content/uploads/2026/04/04-FORMULACION.pdf
4. Instituto Nacional de Tránsito y Transporte Terrestre, lineamientos de planes de movilidad: metodología orientativa para muestreo y conteos clasificados; recomienda registrar varios días hábiles distintos.
   https://intrant.gob.do/movilidad/index.php/pmus/item/download/33_ead1897527a3a782b65766f2fddabb28

No atribuir a la DGTT actual competencias o datos no comprobados: DGTT es una denominación histórica; solicitar a INTRANT / autoridad municipal y, para seguridad vial, DIGESETT.

## Diseño mínimo de levantamiento propio, si no se obtienen los datos

Cuatro puntos propuestos **para validar en mapa y campo**, no localizaciones exactas aprobadas:

- A: extremo UASD / conexión occidental.
- B: Av. Manolo Tavárez Justo / sector comercial central.
- C: conexiones con barrios residenciales y transbordos.
- D: área Oasis / Playa Dorada y entradas laborales.

Para cada punto: dirección de circulación, coordenada, día y fecha, ventana horaria, modo de vehículo, ocupación estimada, abordajes/desembarques observables, intensidad de lluvia, observadores, método y procedencia. Registrar por lo menos varios días hábiles y franjas de punta; medir el ciclo real del bus mediante GPS cuando exista operación comparable. **Cuatro puntos nunca son una encuesta OD representativa de toda la ciudad.**

La importación de conteos con `audit_counts.py` exige procedencia, punto, duración de observación y conteos; números ficticios no son aceptables.

## Umbral para calibrar

- **BLOQUEADO:** ninguna observación verificable o fechas/direcciones no claras.
- **PROVISIONAL:** aforos documentados en 3–4 puntos y un reporte de incertidumbre (intervalos, día y período).
- **CALIBRADO:** múltiples días/horarios, muestra defendible, ajuste contrastado con muestras no utilizadas y OD de referencia.

Nunca emplear las tasas baja/media/alta configuradas como pronósticos de abordajes.
