# Evidencias de las pruebas de aceptación (ENUNCIADO §11)

Generado por [`tests/acceptance/test_aceptacion_s11.py`](../../tests/acceptance/test_aceptacion_s11.py) contra PostgreSQL real, el consumidor real y la API real.
Cada fila indica el resultado esperado del enunciado, lo observado y si la prueba pasó.

| Prueba | Estado | Resultado esperado |
|---|---|---|
| P1 Recibir un evento nuevo | PASA | Una fila actual, visible en API, mapa y análisis |
| P2 Reenviar la misma versión | PASA | No aumenta el número de terremotos |
| P3 Recibir una versión posterior | PASA | Cambian los datos actuales y las agregaciones afectadas |
| P4 Recibir después una versión antigua | PASA | No sustituye a la más reciente |
| P5 Magnitud nula | PASA | Se conserva con tratamiento documentado y se visualiza como ND |
| P6 Coordenadas inválidas | PASA | Cuarentena y motivo; no aparecen puntos inventados |
| P7 Evento marítimo | PASA | Sin país asignado; permanece en el análisis |
| P8 Reiniciar consumidor | PASA | Reanuda sin duplicar los efectos ya persistidos |
| P9 Cerrar el túnel | PASA (panel publicado + túnel ngrok real) | El panel muestra el fallo y conserva/identifica la última lectura |
| P10 Volver a abrir el túnel | PASA (panel publicado + túnel ngrok real) | Se recuperan las consultas automáticamente |
| P11 Reproducción histórica | PASA | Procesa por Kafka sin mezclarla con datos live |

## P1 · Recibir un evento nuevo

**Estado:** PASA

**Esperado:** Una fila actual, visible en API, mapa y análisis

**Pasos y observaciones:**

- Se entrega un evento live nuevo (`e1`, M4,7) al consumidor.
- Decisión del consumidor: NEW.
- `live.event_current` tiene 1 fila.
- `GET /api/eventos` devuelve 1 evento (el mapa lee este endpoint).
- `GET /api/estadisticas` cuenta 1 evento en totales, serie horaria y distribución de magnitud.

```json
{
  "api_eventos": [
    {
      "id": "e1",
      "mag": 4.7,
      "country_id": "ESP",
      "updated": 1794913201000
    }
  ],
  "totals": {
    "period": {
      "start": 1794787200000,
      "end": null
    },
    "filters": {
      "min_mag": null,
      "country_id": null,
      "mode": "live"
    },
    "unit": "terremotos",
    "events": 1,
    "missing": {
      "magnitude": 0,
      "depth": 0
    }
  }
}
```

## P2 · Reenviar la misma versión

**Estado:** PASA

**Esperado:** No aumenta el número de terremotos

**Pasos y observaciones:**

- Se entrega `e1` y después la misma versión 3 veces más.
- Las 3 decisiones son DUPLICATE.
- Total en la API y en estadísticas antes/después: (1, 1) / (1, 1).
- `event_message` conserva 1 sola fila.

```json
{
  "antes": [
    1,
    1
  ],
  "despues": [
    1,
    1
  ]
}
```

## P3 · Recibir una versión posterior

**Estado:** PASA

**Esperado:** Cambian los datos actuales y las agregaciones afectadas

**Pasos y observaciones:**

- Se entrega `e1` M4,1 (updated t) y después la revisión M6,3 (updated t+89 s).
- Decisión: REVISION.
- La API pasa de M4,1 a M6,3 sin duplicar el evento (total 1).
- El histograma de magnitud pasa del intervalo [4,0-4,5) al [6,0-6,5).
- `event_message` guarda las 2 versiones; `event_current` solo la última.

```json
{
  "antes": [
    {
      "id": "e1",
      "mag": 4.1,
      "country_id": "ESP",
      "updated": 1794913201000
    }
  ],
  "despues": [
    {
      "id": "e1",
      "mag": 6.3,
      "country_id": "ESP",
      "updated": 1794913290000
    }
  ],
  "histograma_antes": {
    "4.0": 1
  },
  "histograma_despues": {
    "6.0": 1
  }
}
```

## P4 · Recibir después una versión antigua

**Estado:** PASA

**Esperado:** No sustituye a la más reciente

**Pasos y observaciones:**

- Se entrega `e1` M6,3 (updated t+89 s) y después una versión anterior M4,1 (updated t+1 s).
- Decisión: STALE.
- La API sigue mostrando M6,3 con `updated` = t+89 s.

```json
{
  "api": [
    {
      "id": "e1",
      "mag": 6.3,
      "country_id": "ESP",
      "updated": 1794913290000
    }
  ]
}
```

## P5 · Magnitud nula

**Estado:** PASA

**Esperado:** Se conserva con tratamiento documentado y se visualiza como ND

**Pasos y observaciones:**

- Se entrega `nul` con `mag: null`.
- Se guarda NULL (no 0) y se acepta: no va a cuarentena.
- La API devuelve `mag: null` (sin NaN) y `metadata.null_mag_count = 1`; el panel lo pinta como ND.
- Con `min_mag=0` queda fuera y se cuenta en `null_mag_excluded = 1`.
- Las estadísticas lo cuentan como evento y lo declaran en `missing.magnitude`, sin entrar en el histograma.

```json
{
  "api": [
    {
      "id": "nul",
      "mag": null,
      "country_id": "ESP",
      "updated": 1794913201000
    }
  ],
  "con_min_mag_0": {
    "generated": 1794916800000,
    "last_ingestion": null,
    "mode": "live",
    "count": 0,
    "truncated": false,
    "total": 0,
    "start": 1794787200000,
    "end": null,
    "limit": 5000,
    "offset": 0,
    "next_offset": null,
    "null_mag_count": 0,
    "null_mag_excluded": 1,
    "filters": {
      "min_mag": 0.0,
      "country_id": null
    }
  },
  "totals": {
    "period": {
      "start": 1794787200000,
      "end": null
    },
    "filters": {
      "min_mag": null,
      "country_id": null,
      "mode": "live"
    },
    "unit": "terremotos",
    "events": 1,
    "missing": {
      "magnitude": 1,
      "depth": 0
    }
  }
}
```

## P6 · Coordenadas inválidas

**Estado:** PASA

**Esperado:** Cuarentena y motivo; no aparecen puntos inventados

**Pasos y observaciones:**

- Se entregan `bad1` (latitud 95) y `bad2` (longitud 200).
- Ambos rechazados con motivo `invalid_coordinates`.
- `quarantine_record` guarda 2 filas con motivo, payload original y referencia Kafka.
- `event_current` queda vacía y la API devuelve 0 eventos: no se corrige ni se coloca ningún punto.

```json
{
  "cuarentena": [
    {
      "event_id": "bad1",
      "motivo": "invalid_coordinates: latitude must be between -90 and 90",
      "topic": "sismos.live",
      "offset": 1
    },
    {
      "event_id": "bad2",
      "motivo": "invalid_coordinates: longitude must be between -180 and 180",
      "topic": "sismos.live",
      "offset": 2
    }
  ]
}
```

## P7 · Evento marítimo

**Estado:** PASA

**Esperado:** Sin país asignado; permanece en el análisis

**Pasos y observaciones:**

- Se entregan `mar` (Atlántico, 30°W 0°N) y `tierra` (Madrid).
- `mar` queda con `country_id: null` y estado `unassigned`; `tierra` es ESP.
- Las estadísticas cuentan los 2 eventos y muestran «Sin país asignado» como grupo propio.
- `country_id=none` devuelve solo `mar`.

```json
{
  "api": [
    {
      "id": "mar",
      "mag": 4.6,
      "country_id": null,
      "updated": 1794913201000
    },
    {
      "id": "tierra",
      "mag": 4.2,
      "country_id": "ESP",
      "updated": 1794913201000
    }
  ],
  "grupos": [
    {
      "key": "ESP",
      "name": "España",
      "count": 1
    },
    {
      "key": null,
      "name": "Sin país asignado",
      "count": 1
    }
  ]
}
```

## P8 · Reiniciar consumidor

**Estado:** PASA

**Esperado:** Reanuda sin duplicar los efectos ya persistidos

**Pasos y observaciones:**

- Se procesan 4 mensajes (3 eventos, uno con revisión) y se guarda el estado.
- Se simula el reinicio con relectura completa desde el offset 0 (el consumidor no había confirmado).
- Decisiones en la relectura: ['stale', 'duplicate', 'duplicate', 'duplicate']: ningún efecto nuevo.
- Filas de `event_current`, `event_message`, cuarentena y versiones vigentes: idénticas antes y después.
- En la pila Docker real lo cubren [`tests/integration/test_reconsume_event.py`](../../tests/integration/test_reconsume_event.py) (reset de offsets a earliest y `docker compose restart consumer`) y [`test_failure_scenarios.py`](../../tests/integration/test_failure_scenarios.py) (caída de PostgreSQL sin confirmar offsets).

```json
{
  "estado": {
    "event_current": 3,
    "event_message": 4,
    "quarantine": 0,
    "versiones": [
      [
        "a",
        1794916805000,
        4.4
      ],
      [
        "b",
        1794913201000,
        5.0
      ],
      [
        "c",
        1794913201000,
        null
      ]
    ]
  },
  "decisiones_relectura": [
    "stale",
    "duplicate",
    "duplicate",
    "duplicate"
  ]
}
```

## P9 · Cerrar el túnel

**Estado:** PASA (panel publicado + túnel ngrok real)

**Esperado:** El panel muestra el fallo y conserva/identifica la última lectura

**Pasos y observaciones:**

- Precondición verificada aquí en la API: cada respuesta lleva `metadata.generated` y `last_ingestion`, que el panel usa para identificar la última lectura buena.
- Comprobado en el panel real (Edge, [`tests/e2e/panel_e2e.mjs`](../../tests/e2e/panel_e2e.mjs), ver [`panel-e2e.json`](panel-e2e.json)): con el servicio `api` parado el panel muestra el aviso «No se pudo actualizar», conserva los eventos de la última lectura, indica cuándo fue y marca la API como «Sin respuesta».
- Comprobado también con el túnel ngrok real y el panel publicado en Netlify ([`panel-publicado-watch.json`](panel-publicado-watch.json), 18-nov-2026): al cerrar ngrok el panel mostró el aviso en ~60 s, con estado «Sin respuesta», y conservó 185 eventos idénticos hasta el final del fallo.

```json
{
  "metadata": {
    "generated": 1794916800000,
    "last_ingestion": null,
    "mode": "live",
    "count": 1,
    "truncated": false,
    "total": 1,
    "start": 1794787200000,
    "end": null,
    "limit": 5000,
    "offset": 0,
    "next_offset": null,
    "null_mag_count": 0,
    "null_mag_excluded": 0,
    "filters": {
      "min_mag": null,
      "country_id": null
    }
  }
}
```

## P10 · Volver a abrir el túnel

**Estado:** PASA (panel publicado + túnel ngrok real)

**Esperado:** Se recuperan las consultas automáticamente

**Pasos y observaciones:**

- Comprobado en el panel real ([`panel-e2e.json`](panel-e2e.json)): al arrancar de nuevo el servicio `api`, el aviso desaparece solo en el siguiente refresco, sin recargar la página, y el estado vuelve a «Accesible» o «Datos desactualizados» según `/api/salud`.
- Las lecturas de la API no tienen estado de sesión, de modo que la siguiente consulta recupera el estado completo.
- Comprobado con el túnel ngrok real ([`panel-publicado-watch.json`](panel-publicado-watch.json)): al reabrir `ngrok http --url=<dominio-fijo> 8000` el panel publicado se recuperó solo, sin recargar la página, 183 s después del primer aviso (el tiempo depende de cuánto estuvo cerrado el túnel y del refresco de 60 s). Con el dominio fijo no hizo falta cambiar [`config.json`](../../frontend/public/config.json) ni volver a publicar.

## P11 · Reproducción histórica

**Estado:** PASA

**Esperado:** Procesa por Kafka sin mezclarla con datos live

**Pasos y observaciones:**

- Un evento live (`live1`) está en `live`.
- Se reproducen 3 eventos históricos (topic `sismos.replay`) más los casos controlados duplicado, revisión y antigua.
- Decisiones del consumidor: ['NEW', 'NEW', 'NEW', 'DUPLICATE', 'REVISION', 'STALE'].
- `/api/eventos?mode=replay` devuelve solo h0, h1, h2; `/api/eventos?mode=live` solo `live1`.
- El tiempo de ocurrencia original se conserva y `replay_at` se guarda aparte.
- Un mensaje de replay entregado al consumidor live se rechaza con `mode_mismatch` y va a cuarentena: nunca se mezcla.
- La API devuelve `metadata.mode = replay` y el panel muestra el aviso «REPRODUCCIÓN» ([`panel-replay.png`](panel-replay.png)).

```json
{
  "decisiones": [
    "NEW",
    "NEW",
    "NEW",
    "DUPLICATE",
    "REVISION",
    "STALE"
  ],
  "replay": [
    {
      "id": "h2",
      "mag": 5.2,
      "country_id": "ESP",
      "updated": 1736000000002
    },
    {
      "id": "h1",
      "mag": 5.3,
      "country_id": "ESP",
      "updated": 1736000060001
    },
    {
      "id": "h0",
      "mag": 5.0,
      "country_id": "ESP",
      "updated": 1736000000000
    }
  ],
  "live": [
    {
      "id": "live1",
      "mag": 4.9,
      "country_id": "ESP",
      "updated": 1794913201000
    }
  ]
}
```
