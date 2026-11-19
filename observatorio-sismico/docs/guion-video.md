# Guion del vídeo de demostración (≈ 12–14 min)

Objetivo: mostrar el funcionamiento y que se cumple la rúbrica (ENUNCIADO §13). Cada bloque indica **qué se ve**, **qué se dice** y **dónde está la evidencia** por si hay que enseñarla.

## Antes de grabar (checklist, 10 min)

1. Portátil enchufado y sin suspensión (`powercfg /change standby-timeout-ac 0`).
2. `docker compose up -d` → `docker compose ps`: los 5 servicios `healthy`. `PRODUCER_MODE=live` en `.env`.
3. Túnel: `ngrok http --url=onset-deepen-situation.ngrok-free.dev 8000` (ventana visible).
4. `curl -H "ngrok-skip-browser-warning: 1" https://onset-deepen-situation.ngrok-free.dev/api/salud?mode=live` → `"status":"ok"`.
5. Refrescar las cifras de la memoria: [`scripts/memoria_datos.py`](../scripts/memoria_datos.py) (instrucciones en [`docs/memoria.md`](memoria.md) §10) y revisar que §3.5 y §5 siguen siendo ciertas (hay más días de datos live). La segunda descarga del catálogo reciente ya está hecha (`reciente-2`, 19-nov); si grabas días después, una tercera (`-e RECIENTE_SNAPSHOT=reciente-3`) mediría si el déficit se cierra con las semanas.
6. Abrir en pestañas: panel publicado, [`docs/memoria.md`](memoria.md), una terminal con `docker compose ps`, y [`docs/evidencias/aceptacion-s11.md`](evidencias/aceptacion-s11.md).
7. Cerrar notificaciones; resolución 1080p; micrófono probado.

## Guion

| Min | Bloque | Qué se ve y se hace | Qué se dice | Criterio / evidencia |
|---|---|---|---|---|
| 0:00 | **Presentación** | Portada de [`memoria.md`](memoria.md) y diagrama de la arquitectura | Qué es el observatorio y que son exactamente cinco servicios; solo la API sale a internet | Arquitectura (§1) |
| 1:00 | **Extracción** | `docker compose logs producer --tail 5`; carpeta `data/raw/live`; tabla `ingest.extraction_log` | Consulta cada 60 s al feed de USGS; guarda el original; **98,7 % de publicaciones evitadas**; reintentos; hueco de 19,5 h recuperado sin perder eventos | **Extracción** (§2), [`consultas-y-procedencia.md`](consultas-y-procedencia.md) |
| 2:30 | **Flujo de un evento** | Seguir un `event_id` real: Kafka → `event_message` (payload original) → `event_current` → API → panel | Clave Kafka = `event_id`; offsets tras el COMMIT; una fila por versión y otra por evento | **Modelado** (§4) |
| 4:00 | **Calidad** | [`docs/analisis-calidad.md`](analisis-calidad.md): gráfico de indicadores por conjunto, completitud, cuarentena y actualidad; registro de la revisión `aka2026wupwhh` (M0,9 → M3,5) | Reglas explícitas; ND nunca es 0; negativos se conservan; cuarentena con motivo; cada indicador con su denominador y sin nota global; la exactitud no se puede medir | **Calidad** (§3) |
| 5:30 | **Panel: secciones y filtros** | Pestaña Resumen (indicadores y mapa); filtro M ≥ 4, país «Sin país asignado», fechas; pestaña Eventos y pulsar una fila para abrir su ficha; pestaña Histórico 2025 (18.302 eventos, paginado, filtro por país) | Tamaño por magnitud, color por profundidad, ND hueco; los mismos filtros afectan al resumen, al mapa, a los gráficos y a la tabla; el histórico se pagina en el servidor | **Análisis** (§5), [`analisis/*.png`](evidencias/analisis/), [`secciones/*.png`](evidencias/secciones/) |
| 7:00 | **Gráficos y comparación** | Pestaña Análisis: pasar el ratón por las barras; dispersión magnitud–profundidad (pulsar un punto abre su ficha); tarjeta de comparación histórica; después la tabla de la conclusión 4 en [`memoria.md`](memoria.md) | Media 50,1 frente a mediana 43 (Kamchatka); octubre de 2026 normal salvo el M7,7 de Panamá (Centroamérica 140 frente a 19 esperados); los últimos 20 días quedan por debajo de todo 2025, y una segunda descarga 23 h después solo añadió 5 eventos (+0,9 %): no es publicación tardía rápida, y no se puede decir aún si es actividad real o catálogo incompleto; por eso las «últimas 24 h» se leen con cautela | Conclusiones 1–4 |
| 8:30 | **Pruebas de aceptación** | [`aceptacion-s11.md`](evidencias/aceptacion-s11.md) (tabla de 11 filas) y ejecutar `docker compose run … unittest discover -s tests/acceptance` | Una prueba por fila del enunciado; la base rechaza con `CHECK` un modo ajeno | **§11**, [`aceptacion-s11.md`](evidencias/aceptacion-s11.md) |
| 9:30 | **Reproducción histórica** | Panel con `?mode=replay&range=custom&from=2025-01-01&to=2025-01-03`: banner «REPRODUCCIÓN» | Se procesa por Kafka con su propio topic y esquema; tiempo original más tiempo de reproducción; duplicado, revisión y versión antigua | Fila «Reproducción», [`pila-real.md`](evidencias/pila-real.md) |
| 10:30 | **Túnel: cerrar y reabrir** | Panel abierto; cerrar ngrok con Ctrl+C; esperar al aviso (≈ 1 min); reabrir con el dominio fijo; el aviso desaparece solo | El panel muestra el fallo y conserva la última lectura con su hora; se recupera sin recargar | Filas «Cerrar/Volver a abrir el túnel», [`panel.md`](evidencias/panel.md) |
| 12:00 | **Complejidad y costes** | [`complejidad.md`](evidencias/complejidad.md) y las tablas de §6 y §7 | Índice único frente a diccionario y frente a secuencial; STRtree; agregar en SQL frente a Python; qué pasaría con 100 millones; coste real ≠ cuota gratuita | **Reflexión** (§6–§8) |
| 13:00 | **Cierre** | Tabla de limitaciones y mejoras | Qué no se puede concluir con un día de datos live; qué haría con más tiempo | §5 y §8 |

**Si falla algo en directo:** ver la tabla «Si algo falla durante la defensa» en [`docs/despliegue.md`](despliegue.md). Si el túnel tarda en recuperarse, mostrar el aviso y explicar el refresco de 60 s: es justo la conducta que se evalúa.

## Explicación individual (esquema para preparar a mano)

El enunciado pide dos cosas con voz propia; no las genera nadie por ti.

**1. El flujo completo (≈ 3 min).** Sigue **un evento** de principio a fin y nombra, en cada paso, la propiedad que se garantiza:

1. USGS publica → el productor lo recoge (sondeo de 60 s, hash de contenido, original guardado).
2. Kafka (clave = `event_id`; ack antes de marcar como publicado).
3. Consumidor: valida, clasifica (`NEW/DUPLICATE/REVISION/STALE`), calcula país y calidad, escribe en una transacción y **solo entonces** confirma el offset.
4. PostgreSQL: historial (`event_message`) + estado actual (`event_current`); restricciones que impiden lo ilegal.
5. API: filtros compartidos, instantánea coherente, estadísticas en SQL.
6. Panel: la misma consulta para mapa, tabla y gráficos; fallo visible y última lectura conservada.

**2. Una decisión técnica propia (≈ 2 min).** Elige una y defiéndela con alternativas y con una medida. Ejemplos con datos ya medidos:

| Decisión | Alternativa descartada | Qué medida la respalda |
|---|---|---|
| Estado de versiones en PostgreSQL con índice único | Diccionario en memoria del consumidor | 112 MiB por millón de claves (≈ 11 GiB para 100 M) y se pierde al reiniciar; el índice da 27 µs a 1 M de filas (§6.1) |
| País solo por punto en polígono | Usar `place` o el país más cercano | 9.833 eventos marítimos mal atribuidos por el texto, mediana 105 km a la costa (§3.6) |
| Agregar en SQL desde `event_current` | Contar mensajes o agregar en Python | 3,7× más rápido y 84 MiB menos de memoria a 1 M (§6.3); una revisión no se cuenta dos veces (§3.4) |
| Productor que publica todo y consumidor que rechaza | Filtrar en el productor | Cada rechazo queda con motivo y referencia: 5 no-terremotos aislados, 0 descartes silenciosos (§3.2) |

Elige la que mejor sepas explicar y prepárate para una pregunta de «¿y si…?» (por ejemplo, «¿qué pasa si el consumidor cae entre el COMMIT y el offset?» → reenvío, `DUPLICATE`, sin cambio de estado).
