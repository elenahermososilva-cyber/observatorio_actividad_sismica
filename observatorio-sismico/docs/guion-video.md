# Guion del vídeo (≈ 18 min)

El vídeo recorre la rúbrica del ENUNCIADO §13 **criterio a criterio y, dentro de cada uno, de izquierda a derecha**: Suficiente → Notable → Sobresaliente, enseñando en cada nivel la evidencia que lo demuestra. No se enseña código fuente: solo el panel, los documentos, la terminal con el estado de los servicios y algunas consultas a la base de datos cuando el dato no se puede ver de otra forma.

Cómo leer cada bloque:

- **Pantalla**: lo que tienes que enseñar, en orden.
- **Dices**: el texto literal. Las cifras entre corchetes, como **[en pantalla]**, cambian con los datos en vivo: léelas de la pantalla en ese momento.

---

## Antes de grabar (15 min)

1. Portátil enchufado y sin suspensión: en PowerShell, `powercfg /change standby-timeout-ac 0`.
2. En [`observatorio-sismico/`](../): `docker compose up -d` y luego `docker compose ps`. Los cinco servicios deben salir `healthy`.
3. Túnel en una ventana aparte: `ngrok http --url=onset-deepen-situation.ngrok-free.dev 8000`.
4. Cifras al día. Si grabas más tarde del 19-nov, repite los cuatro scripts de la memoria §10 y avísame para repasar los números:
   [`scripts/memoria_datos.py`](../scripts/memoria_datos.py), [`scripts/graficos_calidad.py`](../scripts/graficos_calidad.py), [`scripts/medir_api.py`](../scripts/medir_api.py), [`scripts/procedencia.py`](../scripts/procedencia.py) y, al final, [`scripts/enlazar_rutas.py`](../scripts/enlazar_rutas.py).
5. Comprueba que el panel publicado tiene el tema oscuro y la pestaña «Histórico 2025». Si no, vuelve a publicarlo (README, «Panel»).
6. **Elige el evento del recorrido** (bloque 3B). Busca uno reciente con varias versiones:
   ```powershell
   docker compose exec postgres psql -U observatorio -d observatorio -c "SELECT event_id, count(*) AS versiones, max(ingested_at) AS ultima FROM live.event_message GROUP BY 1 HAVING count(*) > 1 ORDER BY max(ingested_at) DESC LIMIT 5;"
   ```
   Apunta un `event_id` (en este guion, **EVENTO**) y comprueba que aparece en la pestaña «Eventos» del panel.
7. **Prepara la reproducción** (bloque 3C) para que se vean entrar los eventos y no solo duplicados:
   ```powershell
   docker compose exec postgres psql -U observatorio -d observatorio -c "TRUNCATE replay.event_current, replay.event_message, replay.quarantine_record;"
   ```
8. Pestañas abiertas en el navegador, en este orden:
   1. el panel publicado: https://observatorio-sismico-elena.netlify.app
   2. el repositorio en GitHub, en el README
   3. [`docs/memoria.md`](memoria.md)
   4. [`docs/consultas-y-procedencia.md`](consultas-y-procedencia.md)
   5. [`docs/analisis-calidad.md`](analisis-calidad.md)
   6. [`docs/evidencias/aceptacion-s11.md`](evidencias/aceptacion-s11.md)
9. Una terminal de PowerShell en [`observatorio-sismico/`](../), con letra grande (Ctrl + rueda).
10. Notificaciones desactivadas, pantalla a 1080p y micrófono probado.

Si el usuario de PostgreSQL de tu `.env` no es `observatorio`, cambia `-U` y `-d` en todos los comandos.

---

## 0. Presentación (0:00 – 1:00)

**Pantalla**

1. README del repositorio en GitHub, con la captura del panel arriba.
2. Baja hasta «Arquitectura».

**Dices**

> «Hola. Este es mi Observatorio de actividad sísmica, el proyecto de Big Data del RA1. Recoge en tiempo real los terremotos que publica el Servicio Geológico de Estados Unidos, los pasa por un pipeline con Kafka, los guarda en PostgreSQL y los ofrece a través de una API hecha con FastAPI. Encima hay un panel en Angular, publicado en Netlify, que consulta esa API a través de un túnel de ngrok.
>
> Son exactamente cinco servicios en Docker Compose: productor, Kafka, consumidor, PostgreSQL y la API. De internet solo se puede llegar a la API.
>
> Del curso reutilicé el mapa base y los documentos del enunciado. El backend, las pruebas, la documentación y casi todo el panel los he desarrollado yo.
>
> Voy a recorrer la rúbrica criterio a criterio y, en cada uno, de nivel en nivel, enseñando la evidencia de cada nivel.»

---

## 1. Extracción (1:00 – 4:00)

### 1A · Suficiente: carga básica

**Pantalla**

1. Terminal: `docker compose ps`.
2. Panel publicado, pestaña **Resumen**.

**Dices**

> «Empiezo por la extracción. Los cinco servicios están en marcha y sanos.
>
> Y este es el resultado: en las últimas 24 horas se han cargado **[en pantalla]** terremotos, todos desde mi propia API, nunca directamente desde USGS. La última lectura fue hace unos segundos: el productor consulta el feed de USGS cada minuto.»

### 1B · Notable: carga más exploración

**Pantalla**

1. Terminal: `docker compose logs --tail 5 producer`.
2. Pestaña [`consultas-y-procedencia.md`](consultas-y-procedencia.md): la tabla del histórico 2025 y luego el apartado 3, «Feed en vivo».

**Dices**

> «Cada línea del registro es una consulta al feed: cuántos eventos trae, cuántos son nuevos y cuánto tardó.
>
> Hay tres fuentes. La primera es el **feed en vivo** de las últimas 24 horas. Cada respuesta repite toda la ventana, así que el productor recuerda qué versiones ya publicó: de **324.823** apariciones de eventos en las respuestas solo publicó **1.115** versiones. Se evitó el **99,7 %** de publicaciones repetidas.
>
> La segunda es el **histórico de 2025**: todo el año, en el mundo, magnitud 4 o más y solo terremotos. Lo descargué con la API del catálogo, en doce consultas mensuales. Aquí está cada consulta, con su fecha, su tamaño y su huella SHA-256, y el número recibido coincide con el que anunciaba la API: **18.302** eventos.
>
> La tercera es el **catálogo de países** de Natural Earth, con 177 entidades, que uso para saber en qué país cae cada epicentro.»

### 1C · Sobresaliente: carga más análisis de tipos

**Pantalla**

1. [`memoria.md`](memoria.md), §2.1 «Fuentes, tipos y unidades».
2. Baja a §2.2 «Automatización y robustez» y §2.3, el párrafo del **hueco de ingesta**.

**Dices**

> «Para el nivel sobresaliente analicé los tipos y las unidades de cada campo. Los tiempos llegan en milisegundos Unix y en UTC. La profundidad, en kilómetros. Y la magnitud no es un único tipo: en 2025 casi el 90 % son de tipo *mb*, mientras que en el feed en vivo predominan *ml* y *md*, que son magnitudes regionales de terremotos pequeños. Por eso nunca comparo magnitudes de tipos distintos como si fueran lo mismo.
>
> También tuve en cuenta los límites de la fuente. La API del catálogo no devuelve más de 20.000 eventos por consulta, así que antes de descargar pido el recuento, y si se acercara al límite el script dividiría el intervalo. El mes más grande, julio, tiene 2.684, así que no hizo falta. Nunca se trunca en silencio.
>
> La extracción está automatizada y es robusta: reintentos con espera creciente si USGS falla, y cada respuesta original se guarda comprimida. Lo comprobé con un caso real: el productor estuvo parado 19 horas y media, y como el feed cubre 24 horas, al reanudar recuperó los 155 eventos que faltaban sin perder ninguno. Si una parada superara las 24 horas, el hueco se recuperaría con el catálogo histórico.»

---

## 2. Calidad (4:00 – 7:00)

### 2A · Suficiente: análisis parcial

**Pantalla**

1. [`memoria.md`](memoria.md), §3.1 «Qué se rechaza, qué se señala y qué se transforma».

**Dices**

> «Paso a la calidad. Las reglas son explícitas y están en esta tabla: qué se rechaza, qué se señala y qué se transforma. Lo inválido, como coordenadas fuera de rango o un tipo que no es terremoto, va a cuarentena con su motivo. Lo que es válido pero llamativo, como una magnitud negativa, se conserva y se marca. Y una magnitud que falta nunca se convierte en cero: se queda como "no disponible", ND.»

### 2B · Notable: cuatro o más dimensiones

**Pantalla**

1. Pestaña [`analisis-calidad.md`](analisis-calidad.md): la tabla del apartado 1 y el gráfico de indicadores por conjunto.

**Dices**

> «Analizo seis dimensiones en los tres conjuntos de datos: el feed en vivo, el histórico de 2025 y la reproducción.
>
> Cada barra es un cociente con su numerador y su denominador, y por eso no calculo una nota global: mezclaría eventos con versiones.
>
> La completitud, la unicidad y la consistencia están al 100 %, y no porque las haya limpiado a mano, sino porque las garantiza la propia base de datos con restricciones. La validez del feed en vivo es del **99,2 %**: son los no-terremotos que fueron a cuarentena. La actualidad solo tiene sentido en vivo: el **99,9 %** de las versiones entran en menos de dos minutos.
>
> Y la exactitud no la puedo medir. Que una magnitud sea un número entre −3 y 10 demuestra que está bien formada, no que sea correcta. Lo digo y lo documento, en lugar de inventar un porcentaje.»

### 2C · Sobresaliente: completo más acciones

**Pantalla**

1. [`memoria.md`](memoria.md), §3.2, la tabla «antes / después».
2. Terminal:
   ```powershell
   docker compose exec postgres psql -U observatorio -d observatorio -c "SELECT quarantine_id, event_id, left(reason, 70) AS motivo, kafka_topic, kafka_offset FROM live.quarantine_record ORDER BY quarantine_id;"
   ```

**Dices**

> «Para el sobresaliente, cada comprobación tiene su resultado antes y después y la acción que tomé. Antes significa los archivos originales de USGS, y después, lo que queda en la base de datos.
>
> Por ejemplo: la repetición del feed pasa de 324.823 apariciones a 1.115 versiones. Los nueve tipos que no son terremotos (siete explosiones y dos voladuras de cantera) acaban en cuarentena y ninguno en la tabla de eventos. Y las magnitudes nulas se conservan como nulas.
>
> Aquí está la cuarentena real: cada rechazo tiene su motivo y la referencia exacta del mensaje en Kafka, con su topic y su posición. Se conserva el mensaje original completo, así que no se pierde nada en silencio.»

---

## 3. Modelado (7:00 – 11:00)

### 3A · Suficiente: join básico

**Pantalla**

1. Panel, pestaña **Resumen**. En el filtro «País», elige **Sin país asignado** y pulsa «Aplicar filtros».
2. Pulsa «Restablecer».

**Dices**

> «En el modelado, la integración principal es geográfica: cada terremoto se une con el catálogo de países por su posición, con un cálculo de punto en polígono. Nunca uso el texto descriptivo del lugar ni el país más cercano.
>
> Si el epicentro no cae dentro de ningún país, normalmente porque está en el mar, queda como "Sin país asignado". No es un error y no se descarta: sigue en el análisis como un grupo más, y se puede filtrar por él.»

### 3B · Notable: modelo correcto — recorrido de un evento

Este bloque es también la **explicación individual**: el recorrido de un evento desde USGS hasta el panel.

**Pantalla**

1. [`memoria.md`](memoria.md), §4.1 y §4.2 (modelo conceptual y lógico).
2. Terminal (cambia `EVENTO` por el que apuntaste):
   ```powershell
   docker compose logs consumer | Select-String "EVENTO"
   docker compose exec postgres psql -U observatorio -d observatorio -c "SELECT event_id, updated_ms, payload->'properties'->>'mag' AS mag, ingested_at FROM live.event_message WHERE event_id = 'EVENTO' ORDER BY updated_ms;"
   docker compose exec postgres psql -U observatorio -d observatorio -c "SELECT event_id, mag, country_id, current_version_ms FROM live.event_current WHERE event_id = 'EVENTO';"
   ```
3. Panel, pestaña **Eventos**: pulsa la fila de ese evento para abrir su ficha.

**Dices**

> «El modelo distingue un terremoto de sus versiones, porque USGS revisa los datos después de publicarlos. Hay dos tablas: `event_message`, con una fila por cada versión que llega, y `event_current`, con una fila por terremoto, que guarda solo la versión vigente. La clave de un terremoto es su identificador y la de una versión es el identificador junto con la fecha de actualización de USGS.
>
> Os enseño el recorrido de un evento real. USGS lo publica. El productor lo recoge en la siguiente consulta y lo publica en Kafka, con el identificador como clave, para que las versiones de un mismo terremoto lleguen en orden. El consumidor lo valida y decide si es nuevo, un duplicado, una revisión o una versión antigua. Aquí lo veis: primero entró como nuevo y después llegó una revisión.
>
> En la base de datos hay **[en pantalla]** versiones de este terremoto en `event_message`, pero una sola fila en `event_current`, con la versión más reciente. Al guardarlo se le asigna el país.
>
> Solo después de que la escritura en PostgreSQL se confirma, el consumidor confirma su posición en Kafka. Si se cayera entre una cosa y otra, Kafka le volvería a entregar el mensaje, saldría como duplicado y no cambiaría nada.
>
> Y aquí termina el recorrido: la API lo sirve y el panel lo muestra en su ficha, con la última versión y el país asignado por geometría.»

### 3C · Sobresaliente: modelo optimizado

**Pantalla**

1. [`memoria.md`](memoria.md), §4.5 «Índices y su justificación».
2. Pestaña [`aceptacion-s11.md`](evidencias/aceptacion-s11.md): la tabla resumen.
3. Terminal (deja correr la reproducción unos segundos):
   ```powershell
   docker compose run --rm --no-deps -e PRODUCER_MODE=replay -e REPLAY_INTERVAL_SECONDS=0.5 producer
   docker compose logs --tail 15 consumer
   ```
4. Panel: añade a la URL `?mode=replay&range=custom&from=2025-01-01&to=2025-01-03` y pulsa Intro.
5. Quita el parámetro y vuelve al panel en vivo.

**Dices**

> «Para el sobresaliente, el modelo está optimizado y cada índice se justifica con la consulta que acelera y con una medición. El índice único de versiones baja la búsqueda en un millón de filas de 58 milisegundos a 27 microsegundos. El índice por tiempo baja la ventana de 24 horas de 36 a 2,3 milisegundos. Y también digo lo que un índice no arregla: para agregar el año entero hay que leer todas las filas igualmente.
>
> La idempotencia está probada, no solo programada. Estas son las pruebas de aceptación del enunciado, una por fila, ejecutadas contra PostgreSQL y la API reales. Reenviar la misma versión no suma terremotos. Una versión posterior cambia los datos. Una versión antigua no sustituye a la nueva. Y reiniciar el consumidor no duplica nada.
>
> Por último, el aislamiento por modos. Lanzo ahora la reproducción histórica: envía diez terremotos de 2025 por Kafka y tres casos de control, que son un duplicado, una revisión y una versión antigua. En el registro del consumidor se ve cada decisión: diez nuevos, un duplicado, una revisión y una versión antigua ignorada.
>
> La reproducción va por su propio topic de Kafka y su propio esquema en PostgreSQL, y la base de datos rechaza un mensaje de otro modo aunque se intente con SQL directo. En el panel aparece el aviso "REPRODUCCIÓN", con las fechas originales de 2025, y los datos en vivo no se mezclan.»

---

## 4. Análisis (11:00 – 14:30)

### 4A · Suficiente: uno o dos análisis

**Pantalla**

1. Panel, pestaña **Análisis**, con los filtros por defecto.
2. Pasa el ratón por varias barras del gráfico «Terremotos por hora UTC».
3. En «Por país», pulsa «Subregión» y después vuelve a «País».

**Dices**

> «Paso al análisis. Todos los gráficos se calculan en la base de datos sobre todos los eventos que cumplen los filtros, nunca sobre una muestra.
>
> El primero son las ventanas por hora UTC: recuentos en ventanas fijas de una hora según la hora de ocurrencia. El segundo agrupa por país o por subregión, y "Sin país asignado" aparece siempre como un grupo más.»

### 4B · Notable: tres o más análisis

**Pantalla**

1. En la misma pestaña, baja a las distribuciones de magnitud y profundidad.
2. Pasa el ratón por un punto de «Magnitud frente a profundidad» y púlsalo: se abre su ficha. Pulsa «Volver».
3. Baja a «Comparación con el histórico».
4. Pestaña **Histórico 2025**: elige el país **Japón**, magnitud mínima **5**, y pulsa «Buscar en el histórico».

**Dices**

> «Además están las distribuciones de magnitud y de profundidad, siempre con el número de valores no disponibles a la vista, y la relación entre magnitud y profundidad, en la que cada punto es un terremoto que se puede abrir.
>
> La comparación equivalente es el análisis más delicado. Compara las últimas 24 horas con la media diaria de 2025 usando los mismos filtros en los dos lados. Los días de 2025 sin eventos cuentan en el denominador, y si la media fuera cero mostraría ND en lugar de dividir por cero. Además de la media enseño la mediana y el rango, porque la media se dispara con las secuencias de réplicas.
>
> Y el histórico de 2025 completo se puede consultar paginado desde el servidor, con sus propios filtros. Por ejemplo, Japón con magnitud 5 o más.»

### 4C · Sobresaliente: análisis más insights

**Pantalla**

1. [`memoria.md`](memoria.md), §5: muestra el título de cada conclusión y deja ver la tabla de la conclusión 4.
2. Baja a «Resultado complementario» y a «Qué se puede decir y qué no».

**Dices**

> «Para el sobresaliente, saco conclusiones, cada una con su periodo, sus filtros y su denominador.
>
> Primera: el catálogo está completo a partir de magnitud 4,5. Lo muestra el parámetro *b* de Gutenberg-Richter, que es estable desde 4,5 y cae al incluir 4,0. Por debajo de 4,5 faltan terremotos pequeños.
>
> Segunda: la media diaria de 2025, 50 terremotos, está inflada por la secuencia del terremoto de magnitud 8,8 de Kamchatka. Un solo día de julio tuvo 645. La mediana, 43, describe mejor un día normal.
>
> Tercera: el 78 % de los epicentros no cae en ningún país, y casi todos los profundos están bajo el mar. Por eso "Sin país asignado" es el grupo más grande.
>
> Cuarta: en octubre de 2026 la actividad mundial fue normal, salvo la secuencia del terremoto de magnitud 7,7 de Panamá. Centroamérica tuvo 140 terremotos cuando lo esperable eran 19. En cambio, las últimas tres semanas quedan por debajo de todo 2025. Descargué el catálogo dos veces, con 23 horas de diferencia, y solo aparecieron cinco eventos más. Así que no es un retraso de publicación de unas horas, y con estos datos no puedo saber todavía si es actividad real o un catálogo que se completa durante semanas. Lo dejo como pregunta abierta.
>
> También enseño un resultado que no interpreto: el test estadístico rechaza que los terremotos se repartan igual entre las horas del día, pero el efecto es pequeño y las réplicas rompen la independencia que supone el test, así que no lo presento como un ciclo diario. Y separo lo que se puede afirmar de lo que no.»

---

## 5. Reflexión (14:30 – 17:30)

### 5A · Suficiente: reflexión básica

**Pantalla**

1. [`memoria.md`](memoria.md), §8 «Limitaciones y mejoras».

**Dices**

> «Último criterio, la reflexión. Estas son las limitaciones reales del sistema: depende de mi portátil y de un túnel gratuito; si se para más de 24 horas, el feed no basta para recuperar el hueco; el mapa de países es simplificado, y las magnitudes son de tipos mezclados.»

### 5B · Notable: buena reflexión — decisión técnica propia

Este bloque es la segunda parte de la **explicación individual**: una decisión técnica propia.

**Pantalla**

1. [`memoria.md`](memoria.md), §6.1, la tabla de búsqueda por identificador.
2. §6.2 y §6.3, sus tablas.

**Dices**

> «La reflexión sobre complejidad está medida con tres tamaños o más, con datos sintéticos en una base temporal que no se mezcla con los reales.
>
> La decisión técnica que quiero justificar es dónde guardo el estado de las versiones. La alternativa fácil era un diccionario en la memoria del consumidor, que busca en tiempo constante y es rapidísimo. Pero medí lo que ocupa: 112 megas por cada millón de terremotos, y unos 11 gigas para cien millones, que no caben en un portátil. Además, se perdería al reiniciar. Por eso lo guardo en PostgreSQL con un índice único: la búsqueda es logarítmica, de 8 a 27 microsegundos aunque la tabla crezca mil veces, persiste, y la propia base de datos impide los duplicados.
>
> También medí la integración geográfica, donde un índice espacial es cuatro o cinco veces más rápido que recorrer los 177 polígonos, y la agregación por horas. Agregar en la base de datos en lugar de en Python es 3,7 veces más rápido, y la memoria del cliente baja de 84 megas a menos de uno.»

### 5C · Sobresaliente: excelente reflexión más propuestas

**Pantalla**

1. [`memoria.md`](memoria.md), §6.5 «Qué ocurriría con 100 millones de registros».
2. §7 «Costes».
3. Vuelve a §8 y señala la columna «Cuándo aplicarla».

**Dices**

> «Para el sobresaliente, razono qué pasaría con cien millones de registros. Una búsqueda secuencial tardaría tres segundos por mensaje y sería inviable. El índice único seguiría siendo viable. Y agregar el año completo pasaría a unos 21 segundos por petición, así que habría que precalcular agregados por hora y país, recalculando la ventana afectada cada vez que llega una revisión.
>
> Los costes distinguen lo medido de lo estimado. Lo medido es el almacenamiento: la base de datos ocupa 39 megas y los originales en vivo crecen unos 10 megas al día. Lo estimado es la electricidad, la amortización del portátil y mis horas: unas 32. Que un servicio sea gratuito no significa que el coste sea cero.
>
> Y cada mejora va ligada a un problema concreto y al momento en que la aplicaría: precalcular agregados cuando la latencia supere el refresco de 60 segundos, más particiones de Kafka si un consumidor no da abasto, o reconciliar con el catálogo cuando se detecte un hueco de más de 24 horas.»

---

## 6. Demostración de fallo: cerrar y reabrir el túnel (17:30 – 19:00)

Es la limitación de la que acabo de hablar, demostrada en directo. Corresponde a las filas «Cerrar el túnel» y «Volver a abrir el túnel» del ENUNCIADO §11.

**Pantalla**

1. Panel publicado, pestaña **Resumen**, a la vista.
2. En la ventana de ngrok, pulsa **Ctrl + C**.
3. Espera al aviso rojo (hasta 60 segundos).
4. Vuelve a lanzar `ngrok http --url=onset-deepen-situation.ngrok-free.dev 8000`.
5. Espera a que el aviso desaparezca solo (hasta 60 segundos).

**Dices** (mientras esperas)

> «Ahora cierro el túnel, como si apagara el equipo o se cortara la red. El panel sigue cargando desde Netlify, pero ya no puede hablar con la API.
>
> Aquí está el aviso: el panel dice que no ha podido actualizar, conserva los terremotos de la última lectura correcta e indica cuándo se tomó. No muestra una lista vacía como si no hubiera terremotos.
>
> Vuelvo a abrir el túnel con el mismo dominio fijo. En el siguiente refresco, sin recargar la página, el panel se recupera solo.»

---

## 7. Cierre (19:00 – 19:30)

**Pantalla**

1. README en GitHub, tabla «Dónde está cada entregable».

**Dices**

> «Y con esto termino. En el README del repositorio está dónde se encuentra cada entregable: el código, la memoria, el diccionario de datos, el registro de consultas y procedencia, el análisis de calidad y todas las evidencias de las pruebas. Gracias.»

---

## Si vas justa de tiempo

Estos recortes ahorran unos 3 minutos sin dejar ningún nivel sin evidencia:

- **1C:** di solo la frase de los tipos de magnitud y la del hueco de 19 horas y media.
- **3C:** enseña la tabla de aceptación y el aviso «REPRODUCCIÓN» del panel, sin lanzar la reproducción en directo (está documentada en [`docs/evidencias/pila-real.md`](evidencias/pila-real.md)).
- **4C:** cuenta solo las conclusiones 2 y 4.
- **6:** si el túnel tarda en recuperarse, sigue hablando: la recuperación espera al siguiente refresco de 60 segundos, y esa espera es justo el comportamiento que se evalúa.

## Si algo falla durante la grabación

| Síntoma | Qué hacer |
|---|---|
| El panel dice «Sin conexión con la API» antes de tiempo | Mira la ventana de ngrok y `docker compose ps`; tabla completa en [`docs/despliegue.md`](despliegue.md) |
| «Datos desactualizados» | `docker compose logs --tail 5 producer`; si no hay `cycle ok`, `docker compose restart producer` |
| La reproducción solo da duplicados | No vaciaste el esquema `replay` (paso 7 de la preparación) |
| El evento elegido ya no está en las últimas 24 h | En la pestaña Eventos, elige «Últimos 7 días» o busca otro con la consulta del paso 6 |
