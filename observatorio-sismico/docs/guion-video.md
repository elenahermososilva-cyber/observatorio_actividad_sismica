# Guion del vídeo (≈ 6 min)

El vídeo recorre los criterios de la rúbrica (ENUNCIADO §13) en orden: extracción, calidad, modelado, análisis y reflexión. En cada uno se enseña la evidencia que justifica la nota máxima. No se enseña código fuente: solo el panel, los contenedores, los registros, los documentos y una consulta a la base de datos.

- **Pantalla**: lo que enseñas, en orden. Cambia de pestaña mientras hablas.
- **Dices**: el texto literal. Lo que va entre corchetes, como **[en pantalla]**, cambia con los datos en vivo: léelo de la pantalla en ese momento.

---

## Antes de grabar

1. Portátil enchufado y sin suspensión: `powercfg /change standby-timeout-ac 0`.
2. En [`observatorio-sismico/`](../): `docker compose up -d` y comprueba con `docker compose ps` que los cinco servicios salen `healthy`.
3. Túnel en otra ventana: `ngrok http --url=onset-deepen-situation.ngrok-free.dev 8000`.
4. Abre el panel publicado y comprueba que tiene el tema oscuro, la pestaña «Histórico 2025» y la API «Accesible». Si no, vuelve a publicarlo (README, «Panel»).
5. **Elige el evento del recorrido**: uno reciente con varias versiones. Apunta su `event_id` (en este guion, **EVENTO**):
   ```powershell
   docker compose exec postgres psql -U observatorio -d observatorio -c "SELECT event_id, count(*) AS versiones FROM live.event_message GROUP BY 1 HAVING count(*) > 1 ORDER BY max(ingested_at) DESC LIMIT 5;"
   ```
   Comprueba que aparece en la pestaña «Eventos» del panel.
6. Ten la terminal con letra grande y estos tres comandos a mano para pegarlos (con **EVENTO** ya sustituido):
   ```powershell
   docker compose ps
   docker compose logs --tail 5 producer
   docker compose exec postgres psql -U observatorio -d observatorio -c "SELECT event_id, updated_ms, payload->'properties'->>'mag' AS mag FROM live.event_message WHERE event_id = 'EVENTO' ORDER BY updated_ms;"
   ```
7. Pestañas del navegador, en este orden:
   1. el panel publicado: https://observatorio-sismico-elena.netlify.app
   2. el README en GitHub
   3. [`docs/consultas-y-procedencia.md`](consultas-y-procedencia.md)
   4. [`docs/diccionario-de-datos.md`](diccionario-de-datos.md)
   5. [`docs/analisis-calidad.md`](analisis-calidad.md)
   6. [`docs/memoria.md`](memoria.md)
   7. [`docs/evidencias/aceptacion-s11.md`](evidencias/aceptacion-s11.md)
8. Desactiva las notificaciones, graba a 1080p y prueba el micrófono.

Si grabas después del 19-nov, vuelve a ejecutar antes los scripts de la memoria §10 para que las cifras coincidan.

---

## 1. Presentación y arquitectura (0:00 – 0:40)

**Pantalla**

1. El README en GitHub, con la captura del panel. Baja hasta «Arquitectura».
2. Terminal: `docker compose ps`.
3. El panel publicado, pestaña **Resumen**.

**Dices**

> «Hola, este es mi Observatorio de actividad sísmica: muestra los terremotos que ocurren ahora en el mundo y los compara con 2025.
>
> Un productor consulta cada minuto el feed del Servicio Geológico de Estados Unidos y lo publica en Kafka. Un consumidor valida cada evento, le asigna el país y lo guarda en PostgreSQL sin duplicarlo. Una API en FastAPI calcula las estadísticas, y este panel, en Netlify, las consulta por un túnel de ngrok.
>
> Aquí están los cinco servicios, sanos; solo la API es accesible desde fuera. Y el panel, con **[en pantalla]** terremotos de las últimas 24 horas, se actualiza solo cada minuto.»

---

## 2. Extracción (0:40 – 1:35)

**Pantalla**

1. Terminal: `docker compose logs --tail 5 producer`.
2. [`consultas-y-procedencia.md`](consultas-y-procedencia.md): la tabla de consultas del histórico 2025.
3. [`diccionario-de-datos.md`](diccionario-de-datos.md): la tabla de campos.

**Dices**

> «Uso tres fuentes. La primera, el feed de las últimas 24 horas. En el registro del productor se ve cada consulta: cuántos eventos trae, cuántos publica y cuántos ya había publicado. Como cada respuesta repite el día entero, de 324.823 apariciones solo publicó 1.115 versiones. Si USGS falla, reintenta esperando cada vez más, y cuando el productor estuvo parado diecinueve horas, al volver recuperó los 155 eventos que faltaban.
>
> La segunda, el histórico de 2025, descargado en doce consultas mensuales, cada una con su huella SHA-256: 18.302 eventos, los que anuncia USGS. La tercera, el catálogo de 177 países de Natural Earth.
>
> En el diccionario están los tipos y unidades: tiempos en milisegundos UTC, profundidad en kilómetros, y magnitudes que pueden ser negativas o nulas y de tipos distintos, que no comparo como si fueran lo mismo.»

---

## 3. Calidad (1:35 – 2:30)

**Pantalla**

1. [`analisis-calidad.md`](analisis-calidad.md): la tabla del apartado 1 y el gráfico de indicadores por conjunto.
2. [`memoria.md`](memoria.md), §3.2: la tabla «antes / después».

**Dices**

> «En calidad mido seis dimensiones en el feed, el histórico y la reproducción, cada una con su numerador, su denominador y la decisión tomada. Completitud, unicidad y consistencia están al cien por cien porque las garantiza la base de datos. La validez es del 99,2 % y la actualidad del 99,7 %: casi todo entra en menos de dos minutos. La exactitud no la puedo medir sin otra fuente, y lo digo en vez de inventar una cifra.
>
> En el antes y el después se ve qué hice: nueve eventos que no eran terremotos, explosiones y voladuras, están en cuarentena con su motivo y el original; las magnitudes negativas se conservan marcadas, y una magnitud que falta nunca se rellena con cero.»

---

## 4. Modelado (2:30 – 3:40)

**Pantalla**

1. [`memoria.md`](memoria.md), §4.2: el modelo lógico.
2. Terminal: la consulta de las versiones de **EVENTO**.
3. Panel, pestaña **Eventos**: pulsa la fila de ese evento y enseña su ficha.
4. [`aceptacion-s11.md`](evidencias/aceptacion-s11.md): la tabla resumen.
5. [`memoria.md`](memoria.md), §4.5: la tabla de índices.

**Dices**

> «El modelo separa el terremoto de sus versiones, porque USGS revisa los datos. `event_message` guarda cada versión y `event_current`, una fila por terremoto con la vigente. La clave de una versión es el identificador más su fecha de actualización.
>
> Este es el recorrido de un evento real. USGS lo publica, el productor lo envía a Kafka con su identificador como clave y el consumidor decide si es nuevo, duplicado, revisión o antiguo. Tiene **[en pantalla]** versiones guardadas, pero en el panel aparece una vez, con la última. Y Kafka solo lo da por procesado después de guardarlo, así que un reinicio no duplica nada.
>
> Lo demuestran las pruebas de aceptación contra la pila real: repetir una versión no cambia nada, una antigua no pisa la actual y la reproducción no se mezcla con los datos en vivo.
>
> El país se asigna por punto en polígono, nunca por el texto; si cae en el mar, queda como "Sin país asignado". Y cada índice está medido: el de versiones baja la búsqueda en un millón de filas de 58 milisegundos a 27 microsegundos.»

---

## 5. Análisis (3:40 – 4:45)

**Pantalla**

1. Panel, pestaña **Análisis**. Pon «Magnitud mínima» a **4** y pulsa «Aplicar filtros». Enseña cómo cambian los gráficos.
2. Baja a «Comparación con el histórico».
3. Pulsa «Restablecer». Pestaña **Histórico 2025**.
4. [`memoria.md`](memoria.md), §5: los títulos de las conclusiones.

**Dices**

> «Todo lo que se ve lo calcula la API con SQL sobre todos los eventos; el panel solo lo muestra. Si filtro por magnitud 4 o más, cambian a la vez el mapa, la tabla y las estadísticas: ventanas por hora UTC, recuento por país y distribuciones.
>
> La comparación con 2025 usa los mismos filtros en los dos lados y enseña media, mediana y rango, porque la media sola engaña. Y el histórico completo se consulta aquí, paginado.
>
> Las conclusiones llevan su periodo y su base. En 2025 la media es de 50 terremotos al día y la mediana de 43: la media la infla la secuencia del 8,8 de Kamchatka, con un día de 645. El catálogo es completo desde magnitud 4,5. Y el 78 % de los epicentros cae en el mar. También digo lo que no puedo afirmar: un test horario sale significativo, pero las réplicas rompen sus supuestos, así que no hablo de ciclo diario.»

---

## 6. Reflexión (4:45 – 5:50)

**Pantalla**

1. [`memoria.md`](memoria.md), §6.1: la tabla de búsqueda por identificador.
2. §6.5 «Qué ocurriría con 100 millones de registros».
3. §7 «Costes».
4. §8 «Limitaciones y mejoras».

**Dices**

> «Para la reflexión medí cómo crece el sistema con tres tamaños, con datos sintéticos en una base aparte.
>
> Mi decisión técnica fue guardar el estado de las versiones en PostgreSQL con un índice único, y no en un diccionario en memoria. El diccionario es más rápido, pero ocupa 112 megas por millón de terremotos, unos 11 gigas con cien millones, y se pierde al reiniciar. Con el índice, la búsqueda sigue en microsegundos aunque la tabla crezca mil veces, y la base impide los duplicados.
>
> Con cien millones de registros, y esto ya es un razonamiento, agregar el año tardaría unos 21 segundos, así que precalcularía agregados por hora y país.
>
> En costes separo lo medido, 39 megas de base de datos, de lo estimado, unas 32 horas de trabajo. Y como limitaciones, depende de mi portátil encendido y el feed solo cubre 24 horas; por eso propongo reconciliar con el catálogo si hay un hueco de más de un día.»

---

## 7. Cierre (5:50 – 6:00)

**Pantalla**: el README en GitHub, la tabla «Dónde está cada entregable».

**Dices**

> «Cada criterio, con su evidencia, está enlazado en este README. Gracias.»

---

## Si te pasas de tiempo

- No hagas pausas largas: cambia de pestaña mientras hablas.
- En **2** puedes quitar la frase de los tipos de magnitud.
- En **5** puedes quedarte solo con la conclusión de Kamchatka y la del test horario.
- En **6** puedes quitar la frase de los cien millones de registros.
- No recortes el recorrido del evento (4) ni la decisión técnica (6): son la explicación individual.

## Si algo falla durante la grabación

| Síntoma | Qué hacer |
|---|---|
| El panel dice «Sin conexión con la API» | Mira la ventana de ngrok y `docker compose ps`; tabla completa en [`docs/despliegue.md`](despliegue.md) |
| «Datos desactualizados» | `docker compose logs --tail 5 producer`; si no hay `cycle ok`, `docker compose restart producer` |
| El evento elegido ya no aparece en «Eventos» | Elige «Últimos 7 días» en el periodo, o busca otro con la consulta del paso 5 |
