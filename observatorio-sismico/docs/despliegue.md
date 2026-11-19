# Despliegue y procedimiento de defensa

Arquitectura de la demostración: la pila de 5 servicios corre **en el equipo de la persona que defiende** (Docker Compose). Solo la API se expone a internet, mediante un túnel ngrok. El panel Angular se publica como sitio estático en Netlify y consulta la API a través del túnel.

```
Navegador ──HTTPS──► Netlify (panel estático)
    │
    └──HTTPS (CORS)──► ngrok (dominio fijo) ──► localhost:8000 (API) ──► PostgreSQL ◄── consumidor ◄── Kafka ◄── productor ◄── USGS
```

Kafka y PostgreSQL **no** se publican: Compose solo mapea la API en `127.0.0.1:8000`.

## Datos del despliegue actual

| Elemento | Valor |
|---|---|
| Panel (Netlify, producción) | `https://observatorio-sismico-elena.netlify.app` |
| API pública (ngrok, dominio fijo gratuito) | `https://onset-deepen-situation.ngrok-free.dev` |
| Origen CORS autorizado | `CORS_ORIGINS=http://localhost:4200,https://observatorio-sismico-elena.netlify.app` (en `.env`, que no se versiona) |
| Modo de datos | `PRODUCER_MODE=live`, `API_DEFAULT_MODE=live`, `dataMode: "live"` en [`config.json`](../frontend/public/config.json) |

## Secretos: dónde están y dónde no

- El **authtoken de ngrok** se registró con `ngrok config add-authtoken` en el perfil del usuario de Windows (`%LOCALAPPDATA%\ngrok\ngrok.yml`). No está en el repositorio, ni en el frontend, ni en [`config.json`](../frontend/public/config.json), ni en `.env`.
- La sesión del CLI de Netlify está en el perfil del usuario, fuera del repositorio.
- [`frontend/public/config.json`](../frontend/public/config.json) es **público** (se publica con el sitio): solo contiene la URL pública del túnel, el modo y el intervalo de refresco.
- `.env` no se versiona; [`.env.example`](../.env.example) solo lleva valores de ejemplo.

## Antes de la defensa (checklist)

1. `docker compose up -d` desde [`observatorio-sismico/`](../) y `docker compose ps` con los 5 servicios `healthy`.
2. `PRODUCER_MODE=live` en `.env` (si se cambió, `docker compose up -d --force-recreate producer api`). El productor consulta USGS cada 60 s.
   **Comprobar los datos y la ingesta:** `docker compose logs --tail 3 producer` muestra `cycle ok` cada minuto. El histórico debe estar cargado (18.302 eventos):
   `docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT (SELECT count(*) FROM historico.event_current) AS historico, (SELECT count(*) FROM live.event_current) AS live"'`.
   Si `historico` es 0, cargarlo (README, «Histórico 2025»).
3. Arrancar el túnel **con el dominio fijo**: `ngrok http --url=onset-deepen-situation.ngrok-free.dev 8000`. Con el dominio fijo la URL no cambia al reiniciar ngrok y no hay que recompilar ni volver a publicar.
4. Comprobar `curl -H "ngrok-skip-browser-warning: 1" https://onset-deepen-situation.ngrok-free.dev/api/salud?mode=live` → `"status":"ok"` y `"stale":false`.
5. Abrir el panel publicado y comprobar que el estado de la API es «Accesible», la última ingesta es reciente y hay eventos en mapa, tabla y gráficos.
6. Opcional: `node tests/e2e/panel_published.mjs check https://observatorio-sismico-elena.netlify.app "<ruta de observatorio-sismico>"`.

7. **Tener preparada la reproducción histórica** por si se pide. Se lanza sin parar el productor live:
   `docker compose run --rm --no-deps -e PRODUCER_MODE=replay -e REPLAY_INTERVAL_SECONDS=0.2 producer`
   y se abre el panel con `?mode=replay&range=custom&from=2025-01-01&to=2025-01-03`, que muestra el aviso «REPRODUCCIÓN» sin mezclar datos con los live. Si ya se reprodujo antes, todo sale DUPLICATE o STALE y no cambia nada. Para verla entrar de nuevo, vaciar antes el esquema `replay` (memoria §9.1).

## Volver a publicar el panel

Solo hace falta si cambia el código del panel o la URL del túnel:

```powershell
cd observatorio-sismico\frontend
# editar public/config.json si cambia apiUrl (sin «/api» al final)
npm run build
npx netlify-cli deploy --prod --dir=dist/observatorio/browser --site <SITE_ID> --message "descripción"
```

El sitio se creó con `npx netlify-cli sites:create` y se despliega con el CLI (carpeta ya compilada, sin ejecutar `npm run build` en Netlify). La visibilidad de producción del sitio es **pública** (Netlify crea los sitios nuevos como privados y hay que cambiarlo en *Who can see it*).

## Autorizar otro origen en la API

```bash
# en .env
CORS_ORIGINS=http://localhost:4200,https://observatorio-sismico-elena.netlify.app,https://otro-origen.example
docker compose up -d --force-recreate api
```

Se admiten solo orígenes exactos (nunca `*`). CORS no es autenticación: la API es de solo lectura y pública.

## Si algo falla durante la defensa

| Síntoma en el panel | Causa probable | Qué hacer |
|---|---|---|
| «No se pudo actualizar… No hay conexión con la API» y estado «Sin respuesta» | Túnel cerrado, equipo sin red o API parada | Reabrir ngrok con el dominio fijo; comprobar `docker compose ps`. El panel se recupera solo en el siguiente refresco (≤ 60 s) y mientras tanto conserva la última lectura |
| «Datos desactualizados» | La API funciona pero el productor live no consulta USGS (sin red, USGS caído, productor parado) | `docker compose logs producer`; reiniciar el productor |
| Mapa vacío con filtros por defecto en modo replay | Es lo esperado: los eventos reproducidos conservan su fecha original (2025) | Usar «Fechas concretas» o la URL con `range=custom&from=…&to=…` |
| «This site is private» en el panel | Visibilidad de Netlify en *Private* | *Who can see it* → *Public* para producción |
| El navegador bloquea las peticiones (CORS) | El origen del panel no está en `CORS_ORIGINS` | Añadirlo y recrear `api` |

## Limitaciones

- **Dependencia del equipo local:** si el equipo se apaga o pierde la red, el panel público muestra el aviso de fallo. Es una limitación asumida del enunciado («no se exige un servidor cloud permanente»).
- **Dominio ngrok gratuito:** es fijo mientras la cuenta lo conserve, pero depende del servicio de ngrok y de sus límites del plan gratuito.
- **Interferencia del plan gratuito de ngrok:** las peticiones sin la cabecera `ngrok-skip-browser-warning` pueden recibir una página de aviso en lugar de JSON; el panel la envía siempre (`skipNgrokWarning: true`).
