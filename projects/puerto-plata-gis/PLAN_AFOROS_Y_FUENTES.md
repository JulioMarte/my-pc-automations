# Plan de calibración de demanda y fuentes — Puerto Plata
## Qué se encontró documentalmente
- INTRANT (septiembre 2025) informó intervenciones semafóricas en Manolo Tavárez Justo con Costambar, José Eugenio, José Augusto, Pedro Glisante y la entrada a Montellano. **No son aforos de pasajeros.** https://intrant.gob.do/noticias/intrant-interviene-red-semaforica-en-puerto-plata-para-mejorar-la-movilidad-y-la-seguridad-vial/
- INTRANT (Memoria 2025) menciona carriles exclusivos en hora pico en Manolo Tavárez, con San Marcos, Teleférico, Penetración Portuaria y Costambar. **No ofrece una matriz OD de Puerto Plata.** https://wp.intrant.gob.do/wp-content/uploads/2023/06/Memoria-Institucional-2025.pdf
- INTRANT mantiene una página de proyectos en ciudades que enumera Plan Piloto Puerto Plata en temporada de cruceros. Solicitar memorias técnicas, anexos tabulares, aforos y conteos originales. https://movilidad.intrant.gob.do/index.php/planes-y-proyectos/proyectos-en-ciudades
- Ayuntamiento Municipal Puerto Plata, Plan de Ordenamiento Territorial 2026: informes de diagnóstico, formulación y ubicación de terminales. La existencia de documentos no implica disponibilidad de aforos desagregados. https://ayuntamientopuertoplata.gob.do/transparencia/
- La encuesta domiciliaria de movilidad INTRANT 2025 está definida para el Gran Santo Domingo, no para Puerto Plata. **No extrapolar sus datos directamente.** https://intrant.gob.do/categoria/noticias/intrant-hara-encuesta-de-movilidad-2025-para-seguir-mejorando-el-transito-de-santo-domingo

## Solicitud documental a INTRANT, DIGESETT, Ayuntamiento y operadores
1. Aforos de pasajeros, ascensos, descensos y cargas por parada/sentido y hora en Puerto Plata, indicando fecha, método, identificación de ruta y muestra.
2. Estudios de origen-destino, encuesta de movilidad local, aforos vehiculares por movimiento en intersecciones y ciclos semafóricos, desde 2023.
3. Geometría de giros, planos de mediana, restricciones de ancho y circulación de autobuses en Luis Ginebra, Manolo Tavárez y terminales candidatas.
4. Servicios actuales, intervalos de salida, recorridos formales/informales y flota operativa.
5. Condiciones de difusión: licencias, resolución espacial, anonimización y representatividad.

## Cuatro puntos de conteo exploratorio (verificar paradas y permisos antes de medir)
A. Entorno UASD / terminal occidental propuesta: origen de viajes universitarios y transbordos.
B. Manolo Tavárez Justo / acceso San Marcos: conexión residencial y posibles alimentadoras.
C. Manolo Tavárez Justo / calle del Teleférico: flujo transversal y acceso residencial.
D. Entorno Oasis / Playa Dorada: destino turístico, servicio y retorno propuesto.

La ubicación de estos puntos es una **propuesta de diseño de muestra**, no una afirmación de ubicación oficial de paradas. Antes del operativo confirmar seguridad y visibilidad.

### Protocolo mínimo
- Contar por separado ambos sentidos, incluyendo subidas, bajadas, vehículos y ocupación aparente (solo cuando sea fiable).
- Bloques sugeridos: 06:30–09:00, 12:00–14:00, 16:30–19:30; al menos dos días laborables y un sábado como primera exploración. Ampliar posteriormente para estimar variabilidad.
- Registrar fecha, minuto de inicio, duración observada, sentido, clima, interrupciones, ruta, método y observador.
- Evitar fotografiar rostros o guardar identificadores personales.
- Integrar con `audit_counts.py` y luego un esquema ampliado que incorpore dirección, fecha y conteo de vehículos.
- No transformar 3–4 puntos de observación en estimación de demanda municipal: calibrar únicamente los movimientos realmente observados y reportar intervalos de incertidumbre.

## Estado
**Aforos solicitables identificados; no se ha obtenido ninguna base local de abordajes públicos con procedencia verificable. Calibración real BLOQUEADA.**
