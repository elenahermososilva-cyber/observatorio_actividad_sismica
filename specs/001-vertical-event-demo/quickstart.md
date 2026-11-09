# Guía rápida de validación para la primera entrega vertical

## Objetivo

Validar que un evento sintético entra en el sistema, se persiste con idempotencia y puede consultarse a través de la API con el formato GeoJSON del contrato.

## Prerrequisitos

- Docker y Docker Compose disponibles en el equipo.
- Repositorio clonado y preparado.
- Frontend entregado ya presente en `observatorio-sismico/frontend`.
- No se requieren credenciales reales para la demostración local.

## Preparar la configuración local

Desde la raíz del repositorio, crea los archivos ignorados de configuración local a partir de sus plantillas:

```powershell
Copy-Item observatorio-sismico\backend\producer\.env.example observatorio-sismico\backend\producer\.env
Copy-Item observatorio-sismico\backend\consumer\.env.example observatorio-sismico\backend\consumer\.env
Copy-Item observatorio-sismico\backend\api\.env.example observatorio-sismico\backend\api\.env
Copy-Item observatorio-sismico\backend\db\.env.example observatorio-sismico\backend\db\.env
```

La contraseña local de PostgreSQL debe coincidir en los archivos de consumidor, API y base de datos. Los `.env` no se versionan; las plantillas solo contienen valores de demostración.

## Validación de servicios

1. Ejecuta la composición mínima desde la carpeta `observatorio-sismico/`:
   ```bash
   cd observatorio-sismico
   docker compose up --build -d
   ```
   El archivo de composición esperado es `observatorio-sismico/compose.yaml`.
2. Verifica el estado de los cinco servicios obligatorios:
   ```bash
   docker compose ps
   ```
3. Comprueba que están levantados los servicios de productor, Kafka, consumidor, PostgreSQL y API.

**Resultado esperado**: todos los servicios aparecen activos y sin errores de arranque.

## Publicación y consumo del evento de prueba

1. El servicio productor publica el evento `demo-evt-001` con `source = synthetic-demo`, `mode = demo` y `synthetic_flag = true`.
2. Verifica que el consumidor lo procesa y lo persiste.
3. La prueba de integración publica de nuevo exactamente el mismo mensaje y comprueba la idempotencia.

**Resultado esperado**: la base almacena una sola versión activa para ese evento y no duplica el resultado visible.

## Consulta API

1. Consulta el endpoint del contrato:
   ```bash
   curl http://localhost:8000/api/eventos
   ```
2. Comprueba que la respuesta es un JSON válido con `type: "FeatureCollection"`.
3. Revisa que el evento de prueba aparece exactamente una vez.
4. Comprueba en las propiedades `source = synthetic-demo` y `synthetic_flag = true`; país se mantiene `null` en esta fase, que no implementa enriquecimiento geográfico.

**Resultado esperado**: el evento de prueba aparece una sola vez en `features` y la respuesta sigue el esquema del contrato.

## Prueba automatizada del recorrido vertical

Desde la raíz del repositorio, instala las dependencias de prueba y activa la prueba que requiere la pila Docker:

```powershell
python -m pip install -r observatorio-sismico\tests\requirements.txt
Set-Location observatorio-sismico
$env:RUN_DOCKER_INTEGRATION = "1"
python -m pytest tests\contract\test_api_eventos.py tests\integration\test_vertical_demo.py
```

## Validación de errores explícitos

1. Provoca temporalmente un fallo de escritura a PostgreSQL mientras el consumidor procesa un mensaje válido. Comprueba en el registro del consumidor que la escritura falló y que no se confirmó el offset.
2. Restablece PostgreSQL o reinicia el consumidor para permitir el reintento. Comprueba que el mismo mensaje se vuelve a procesar y queda persistido una sola vez.
3. Envía un mensaje inválido o no soportado. Comprueba que se almacena duraderamente en cuarentena con el motivo y una referencia al payload original antes de confirmar su offset.
4. Comprueba por separado la consulta API: una consulta correcta sin resultados devuelve `200` y `features: []`; una consulta fallida devuelve un error HTTP explícito, no un `FeatureCollection` vacío.
5. Comprueba que `/api/salud` solo informa del estado observable de la API y sus dependencias, sin afirmar que conoce el fallo del consumidor.

**Resultado esperado**: los errores transitorios de escritura se registran y se reintentan sin confirmar el offset; los rechazos se conservan en cuarentena antes de confirmar; la API distingue una consulta exitosa vacía de un fallo de consulta y no atribuye al consumidor un estado que no recibe.

## Criterios de aceptación de la fase

- **SC-001**: los cinco servicios obligatorios están disponibles y el evento sintético consultado aparece exactamente una vez mediante la API.
- El evento sintético se procesa y persiste una sola vez como estado actual.
- El reconsumo del mismo evento no duplica el resultado visible.
- La API devuelve un GeoJSON `FeatureCollection` válido conforme al contrato.
- Los errores se distinguen explícitamente de un resultado vacío válido.
- La validación no exige todavía USGS live, histórico completo ni despliegue en Netlify.

## Limitaciones de esta guía

- No incluye ingestión automática de USGS ni históricos completos.
- No incluye estadísticas ni filtros avanzados.
- No incluye despliegue real ni publicación en Netlify.
- El criterio SC-001 se define en términos binarios y verificables: disponibilidad de servicios y consulta exacta del evento sintético una sola vez.
