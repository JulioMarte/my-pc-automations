# Auditoría preliminar GIS (11 octubre 2026)

Fuente: Workflow OSMnx https://github.com/JulioMarte/my-pc-automations/actions/runs/38161118477 ; WorldPop 2025 modelado, L1 OSRM provisional (22 paradas).
Grafo vehicular: 3,109 nodos / 8,096 aristas; peatonal: 4,116 nodos / 11,152 aristas. Caja de estudio WGS84 oeste -70.752, sur 19.740, este -70.620, norte 19.836. No es un límite administrativo.

Resultados experimentales, NO definitivos:
- Residentes modelados dentro de caja: 103,004; fuera de caja vial pero dentro del recorte de WorldPop: 60,170.
- Cobertura L1 geométrica a 500m de radio: 41,114 residentes modelados.
- Modelo conservador peatonal basado en nodo más cercano y recorridos dirigidos: 17,779 residentes a 500m, con exclusión de celdas a más de 130 m de cualquier nodo de la red.
- Para 250m: 17,148 geométricos / 4,624 peatonales. Para 800m: 64,618 / 38,114.
- 5,805 residentes dentro de caja excluidos por estar sus celdas a más de 130m de nodo caminable. Una parada se encuentra a 195m de un nodo.

IMPORTANTE: 17,779 no es una medición definitiva de acceso. Snapping a nodos introduce desvíos artificiales, principalmente en segmentos largos. Recalcular proyectando cada origen y parada sobre las aristas peatonales, incorporando distancias parciales de segmentos. OSM no acredita calidad de aceras, pasos de peatones ni cruces seguros.

Exploración de nodos densos desatendidos y enlaces de recorrido corto en grafo drive:
1. Norte-centro, 19.795381,-70.693554, concentración local estimada 2,902, enlace cartográfico dirigido a parada propuesta 07 de ~993m.
2. Oeste, 19.788038,-70.726295, concentración local estimada 2,218, enlace cartográfico dirigido a parada propuesta 03 de ~1,890m.

Ninguno constituye una ruta completa y ninguno ha sido validado para circulación de buses o demanda origen-destino. No sumar los valores de zonas candidatas como población adicional de rutas completas. Para decidir L2 o L3 faltan: conectividad a aristas, datos de empleo/escuelas/hospitales/comercios, matriz origen-destino, restricciones de ancho/giros, viajes ida y vuelta, tiempo y flota.
