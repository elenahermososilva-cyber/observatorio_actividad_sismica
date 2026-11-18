# Mediciones de complejidad (datos SINTÉTICOS, base temporal; no mezclados con datos reales)

Generado: 2026-11-18T18:38:29+00:00. Equipo: {"nota": "Mediciones dentro de un contenedor Docker (Docker Desktop sobre WSL2); el equipo anfitrión se documenta en la memoria.", "cpu_visible_en_contenedor": "11th Gen Intel(R) Core(TM) i3-1115G4 @ 3.00GHz", "nucleos_visibles": 4, "ram_visible_mib": 7769, "python": "3.12.16", "shapely": "2.2.0", "postgresql": "17.2 (Debian 17.2-1.pgdg120+1)", "repeticiones_por_medida": 5, "estadistico": "mediana"}

## A. Búsqueda de versiones por identificador (tiempo por búsqueda, mitad aciertos y mitad fallos)

| N | Lista (secuencial) | Diccionario | PostgreSQL sin índice | PostgreSQL con índice único | Memoria lista | Memoria dict | Tabla | Índice |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 26.86 µs | 0.06 µs | 58.00 µs (Seq Scan) | 8.00 µs (Index Only Scan) | 0.14 MiB | 0.1 MiB | 0.05 MiB | 0.05 MiB |
| 10,000 | 292.36 µs | 0.06 µs | 578.50 µs (Seq Scan) | 11.00 µs (Index Only Scan) | 1.37 MiB | 1.01 MiB | 0.57 MiB | 0.4 MiB |
| 100,000 | 2.737 ms | 0.05 µs | 5.934 ms (Seq Scan) | 11.50 µs (Index Only Scan) | 14.19 MiB | 12.66 MiB | 5.74 MiB | 3.89 MiB |
| 1,000,000 | 31.315 ms | 0.06 µs | 58.583 ms (Gather) | 27.00 µs (Index Only Scan) | 144.22 MiB | 112.2 MiB | 57.44 MiB | 38.7 MiB |

## B. Integración geográfica (punto en polígono, 177 polígonos)

| Puntos | Recorrido de 177 polígonos | STRtree | Aceleración | STRtree puntos/s |
|---:|---:|---:|---:|---:|
| 1,000 | 58.842 ms | 13.505 ms | 4.4× | 74,046 |
| 5,000 | 361.267 ms | 68.275 ms | 5.3× | 73,233 |
| 20,000 | 1.22 s | 278.136 ms | 4.4× | 71,907 |
| 100,000 | — | 1.74 s | — | 57,375 |
| 500,000 | — | 7.84 s | — | 63,802 |

Discrepancias entre ambos métodos en 2.000 puntos: 0.
Memoria (RSS del proceso): {"lista_de_177_poligonos_mib": 1.0, "indice_strtree_con_sus_geometrias_mib": 0.9, "catalogo_geojson_mib": 0.8}

## C. Agregación por ventanas de una hora UTC

| N eventos | Ventana 24 h sin índice | Ventana 24 h con índice | Año completo sin índice | Año completo con índice | Agregar en PostgreSQL | Agregar en Python | Pico Python | Tabla | Índice |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10,000 | 670.00 µs ['Seq Scan'] | 38.00 µs ['Bitmap Heap Scan', 'Bitmap Index Scan'] | 2.978 ms | 2.995 ms | 7.272 ms | 6.823 ms | 1.34 MiB | 0.6 MiB | 0.2 MiB |
| 100,000 | 9.017 ms ['Seq Scan'] | 236.00 µs ['Bitmap Heap Scan', 'Bitmap Index Scan'] | 31.595 ms | 23.280 ms | 22.310 ms | 60.378 ms | 8.89 MiB | 5.7 MiB | 2.2 MiB |
| 1,000,000 | 36.494 ms ['Seq Scan'] | 2.330 ms ['Bitmap Heap Scan', 'Bitmap Index Scan'] | 214.367 ms | 214.353 ms | 227.997 ms | 839.711 ms | 84.42 MiB | 57.4 MiB | 21.4 MiB |
