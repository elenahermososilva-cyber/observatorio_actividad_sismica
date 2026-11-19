# Evidencias del panel (Fase 11)

Panel Angular 20.3 + Leaflet servido con `npm start` en `http://localhost:4200`, consultando la API real en `http://localhost:8000`.

## Capturas
Todas las capturas de página completa se regeneran con la interfaz actual (pestañas, indicadores y fichas) mediante `node tests/e2e/capturas_memoria.mjs <url-del-panel> <ruta>`, que fija los filtros por URL y escribe `capturas-memoria.json` con el total del mapa y el de los gráficos de cada captura (coinciden en las seis).
- `panel-live.png`: pestaña Resumen, modo en vivo, filtros por defecto (últimas 24 h): indicadores, filtros y mapa con su leyenda.
- `panel-replay.png`: `?mode=replay&range=custom&from=2025-01-01&to=2025-01-03`. Muestra el banner «REPRODUCCIÓN» y los 10 eventos reproducidos de esos 3 días.
- `analisis/01…04`: las capturas de las conclusiones (filtros visibles en cada una); ver la memoria §5. Las de gráficos usan la pestaña Análisis y las de mapa, la pestaña Resumen.

Los filtros también se pueden fijar por URL (`range`, `from`, `to`, `min_mag`, `country`), lo que permite reproducir exactamente cada captura que se use en las conclusiones de la memoria.

## Prueba en navegador real (`tests/e2e/panel_e2e.mjs`, resultado en `panel-e2e.json`)
Edge headless controlado por el protocolo DevTools, contra la pila real. 17 comprobaciones, todas correctas:
- carga inicial: eventos dibujados, estadísticas, 4 gráficos, tabla con filas, leyenda con ND;
- coherencia mapa↔gráficos: con `min_mag=4`, con «Sin país asignado» y con el rango completo del 17-nov el total del mapa coincide con el de las estadísticas (6/6, 4/4, 219/219);
- el histograma de profundidad es continuo (intervalos de 10 km sin huecos);
- una magnitud mínima inválida muestra un error sin consultar la API;
- **fila 9:** con el servicio `api` parado el panel muestra «No se pudo actualizar», conserva los eventos, indica la hora de la última lectura correcta y marca la API como «Sin respuesta»;
- **fila 10:** al arrancar de nuevo la API el aviso desaparece solo, sin recargar la página.

## Panel publicado en Netlify y túnel ngrok real (Fase 12)

Panel: `https://observatorio-sismico-elena.netlify.app`. API: `https://onset-deepen-situation.ngrok-free.dev` (dominio fijo gratuito de ngrok). Script: `tests/e2e/panel_published.mjs`.

- **`check`** (`panel-publicado-check.json`, 7/7): desde un Edge real y con el origen de Netlify, el panel carga eventos reales a través del túnel, indica «EN VIVO», no muestra avisos, la API figura «Accesible», hay estadísticas, gráficos y tabla, y la última ingesta de USGS tiene menos de 5 minutos.
- **`watch`** (`panel-publicado-watch.json`, 5/5): el equipo cerró ngrok y lo reabrió con el mismo dominio. El panel mostró «No se pudo actualizar… No hay conexión con la API», con la hora de la última lectura correcta y estado «Sin respuesta». Conservó los 185 eventos de la última lectura hasta el final del fallo y se recuperó solo, sin recargar la página, 183 s después del primer aviso.

Historial honesto: el primer intento de `watch` (`panel-publicado-watch-intento1.json`) dio 4/5. La comprobación que falló era un defecto del script, que comparaba con el recuento del arranque de la prueba y no con el último recuento antes del fallo (entre medias el panel había incorporado eventos nuevos de forma normal). Se corrigió el script y se repitió la prueba física, que dio 5/5.

Las filas 9 y 10 de la tabla de aceptación (ENUNCIADO §11) quedan así comprobadas con el panel publicado y el túnel real. Quedan sin probar con ngrok real, por su naturaleza, los reinicios de URL con un dominio no reservado (no aplica mientras se use el dominio fijo).

## Panel por secciones (pestañas, fichas e histórico)

`tests/e2e/panel_secciones.mjs` (Edge headless real contra la API real; no para ningún servicio) → `panel-secciones.json`, **21/21**:
cinco pestañas con la sección activa en la URL; el resumen muestra indicadores e indicador de conexión; los gráficos de
barras muestran el valor de la barra señalada; la dispersión magnitud–profundidad muestra el evento señalado y, al pulsarlo,
abre su ficha; una fila de la tabla abre su ficha (con mapa del epicentro y enlace a la página oficial de USGS) y «Volver»
regresa a la pestaña de origen; la pestaña «Histórico 2025» trae de la API el total de 18.302 eventos, pagina en el servidor
(25 por página, «Siguiente» trae otra página) y aplica filtros de país y magnitud en el servidor (Japón, M ≥ 5: 5 eventos);
la ficha de un evento del histórico indica su procedencia. Las comprobaciones previas (`panel_published.mjs check`, 7/7)
siguen pasando con la nueva estructura: los avisos de fallo y el estado de la API no dependen de la pestaña abierta.

Capturas (`secciones/`): `01-resumen`, `02-analisis`, `03-dispersion`, `04-ficha-evento`, `05-historico`,
`06-historico-japon-m5`, `07-ficha-historico`, `08-estado`.
