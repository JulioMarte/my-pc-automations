# AGENTS.md — Puerto Plata Transit GIS

> Alcance: este directorio y sus subdirectorios. Instrucciones para cualquier agente de desarrollo, investigación o Codex que trabaje en el subproyecto. Idioma de reportes: español.

## Misión y regla de verdad

Construir un **laboratorio local, reproducible y auditable** para comparar corredores y redes de transporte público de Puerto Plata: seguridad vial, acceso peatonal, accesibilidad entre barrios y destinos, demanda con incertidumbre, flota, frecuencia y costos. Generar JSON/GeoJSON/Parquet y visores HTML sencillos. **No presentar propuestas, simulaciones o rutas de OSRM/OSMnx como aprobaciones operativas.**

**L1 = UASD → Av. Manolo Tavárez Justo → Oasis → Playa Dorada**, línea base obligatoria *solo en el brazo A del experimento*. Brazo B debe permitir redes **sin L1**. Nunca declarar que L1 es la mejor ruta basándose únicamente en habitantes dentro de 500 m.

## Lectura obligatoria antes de editar

1. `study_config.json`: **única fuente central** de vehículos, intervalos 10/15/20 min, reserva, penalizaciones, presupuestos y referencias de datos.
2. `PROJECT_STATUS_AND_HANDOFF.md`: estado empírico, resultados verificables, bloqueos y prioridad de trabajo.
3. `VEHICLE_AND_ACCEPTANCE_AUDIT.md`: datos del Citaro K y límites de maniobra.
4. `AFOROS_Y_CALIBRACION.md` y `PLAN_AFOROS_Y_FUENTES.md`: fuentes e incertidumbre de demanda.
5. `LOCAL_STACK_AND_GATES.md`, `R5PY_LOCAL.md`, `SYNTHETIC_OD.md` y `NETWORK_SCENARIO_GUIDE.md`.

Verificar siempre la **rama actual**, `git status`, historial reciente, contenidos de scripts y conclusión **de cada job**, además de abrir los artefactos antes de anunciar un resultado.

## Jerarquía de evidencias (obligatoria)

- `OBSERVADO`: aforo medido, encuesta con metadatos, GPS o levantamiento físico documentado.
- `MODELADO_CON_DATOS`: WorldPop, Overture, OSM, DEM y NASA POWER, con resolución, fuente, fecha y límites.
- `SIMULADO_CALIBRADO`: modelo contrastado con observaciones fuera de muestra y métricas de error.
- `EXPLORATORIO_NO_CALIBRADO`: velocidades 12/18/24 km/h, pausas, frecuencias, OD gravitacional y captura baja/media/alta son **hipótesis**, no previsiones ni pasajeros reales.
- `BLOQUEADO_CON_EVIDENCIA`: ejecución fallida o datos faltantes, con diagnóstico/logs/reproducción.

No rellenar vacíos con números razonables ni reinterpretar `exit 0` como aceptación. **Si un job genera un JSON `BLOCKED_WITH_EVIDENCE`, registrar bloqueo aunque Actions sea verde.**

## Seguridad y validación de autobuses

Vehículo de referencia: **Mercedes-Benz Citaro K**; ficha oficial vinculada en `study_config.json`. Longitud 10.633 m, anchura 2.55 m, con espejos 2.95 m, círculo de giro 17.284 m. Medio diámetro 8.642 m **NO** es radio del espacio barrido. Variante/capacidad, pendiente máxima con carga, barrido dinámico, terminales y compatibilidad regulatoria **no validados**; NO asignar valores por defecto. Mantener `datasheet_verified:false` hasta corroboración completa.

`pyvalhalla` corre localmente sobre **tiles OSM auténticos**, no requiere HTTP. El motor puede comprobar rutas sobre restricciones OSM, pero **no certifica** aperturas de mediana, radios de intersección ni maniobras con voladizos y espejos. Para Luis Ginebra, documentar punto, candidata, vehículo, restricción, evidencia y corrección/descartada/requiere campo; sin datos, `NO_VERIFICADO`, nunca `VIABLE`.

Los giros prohibidos y accesos físicamente inviables son criterios duros *cuando están probados*. Sinuosidad ~1.4 y pendiente orientativa ~10–12 % son **penalizaciones configurables**, no prohibiciones universales; la pendiente máxima física depende de ficha técnica real.

## Pipeline y orden de trabajo

1. **Vehículo**: ficha comercial comprobada, geometría de barrido, pendiente operativa, documentación de variante.
2. **Valhalla real**: revisar `run_local_valhalla_evidence.py` y `build_valhalla_local_tiles.py`, generar tiles desde PBF; auditar ida/vuelta Y transición en terminales; entregar CSV candidato, lat/lon, motivo, vehículo, decisión. No ocultar fallos.
3. **CRS y GIS**: EPSG:32619 para medidas (`validate_spatial.py`); GeoJSON puede conservar WGS84 de origen. Corregir geometrías inválidas y estudiar límites del recorte.
4. **Control con/sin L1**: cobertura **por misma celda** sin doble conteo, métricas por rutas y redes; documentar sesgo de objetivos basados solo en población.
5. **Flota y frecuencia**: `prepare_optimization_input.py` exige `route_id,cycle_minutes,cycle_source,operational_geometry_approved`; `optimize_headways.py` usa OR-Tools con 10/15/20 minutos, reserva y presupuestos 10/20/30; `--exploratory` solo si queda marcado como tal. Ciclos observados o simulados calibrados necesarios para recomendación operativa.
6. **Demanda con incertidumbre**: solicitar conteos y OD a INTRANT, Ayuntamiento y operadores; usar `audit_counts.py`. Diseñar conteos propios seguros en 3–4 puntos de L1, varios sentidos/horarios/días; no extrapolar muestra pequeña a toda la ciudad.
7. **H3/GTFS/r5py**: zonas, destinos y transbordos; R5 local con PBF/GTFS real para tiempos puerta a puerta, accesibilidad 15/30/45 min, transferencia y equidad.
8. **Reporte y visor**: exportar reportes con escenarios, supuestos, sensibilidad, versión de insumos, fecha, errores, bloqueos y comparadores; HTML solo visualiza, no duplica el cálculo.

## Reglas de cambios, pruebas y entrega

- Cada corrección debe incluir tests de éxito **y de fallo**. Preferir módulos y JSON pequeños; evitar despliegue permanente de servidores. Mantener casos de error auditables.
- GitHub Actions verde **no equivale** a fase APROBADA. `phase_gates.py` tiene precondiciones y exige aceptación documental; no fabricar firmas ni identificadores de revisión.
- Los artefactos de etapas anteriores deben reutilizarse; cuidar licencias, cachés, reproducibilidad y consumo de Overpass.
- No exponer secretos, identificadores personales de viajeros ni hacer inferencias sobre viajes de personas concretas.
- Nunca mezclar viajes observados con demanda simulada; nunca reportar `buses` reales usando velocidades hipotéticas.
- En la entrega final, indicar: archivos modificados, SHA de commit, CI/job/artifact examinado, qué pasó realmente, estados `APROBADO/BLOQUEADO`, métricas y límites, siguiente bloqueo prioritario.
- **No fusionar a `main` ni declarar una ruta aprobada sin evidencia y autorización explícita.** Trabajar en `feat/puerto-plata-transit-gis` salvo nueva instrucción.

## Comandos orientativos

```bash
cd projects/puerto-plata-gis
python -m unittest -v test_audit_counts.py test_optimize_headways.py test_prepare_optimization_input.py test_valhalla_local.py test_r5_accessibility.py
python phase_gates.py
# Solo cuando los artefactos de entrada estén disponibles:
python validate_spatial.py
python run_exploratory_curve.py      # MODELO EXPLORATORIO, NO FLOTA REAL
python r5_accessibility.py --help     # PBF y GTFS requeridos para tránsito
python run_local_valhalla_evidence.py --help # PBF y trazados requeridos
```

## Prohibiciones contra autoengaño

- No cerrar un gate basándose solo en presencia de archivos o CI.
- No presentar las coberturas 19,046/19,707/41,114 como ridership o censo ONE.
- No fijar L1 en todos los escenarios.
- No llamar al resultado Valhalla de solo extremos «giro validado».
- No pasar de escenarios exploratorios a inversión en flota sin tiempos/costos/calibración y revisión física.
