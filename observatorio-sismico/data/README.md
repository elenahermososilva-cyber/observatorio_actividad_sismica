# Datos originales y retención

Esta carpeta es la **ubicación documentada de los datos originales** (enunciado §5 y §12). En Git solo se versiona este README: `data/raw/` está en `.gitignore` y se regenera con los comandos de abajo. Dentro de los contenedores es `/app/data/raw` (montaje `./data/raw`).

| Contenido | Ubicación | Cómo se regenera |
|---|---|---|
| Respuestas originales del feed `all_day.geojson` | `data/raw/live/AAAA/MM/DD/HHMMSS.geojson.gz` (gzip, bytes íntegros) | las conserva el productor en modo `live` |
| Histórico 2025 (M ≥ 4, mundo, `earthquake`) | `data/raw/historico/AAAA-MM.geojson` + `manifest.json` | `docker compose run --rm --no-deps producer python -m backend.producer.history_download` |
| Catálogo reciente 2026 para la comparación equivalente (1-oct → 18-nov exclusivo, M ≥ 4, mundo, `earthquake`) | `data/raw/reciente/*.geojson` + `manifest.json` (una segunda instantánea opcional en `data/raw/reciente-2/`) | `scripts/comparacion_reciente.py` (comando en `docs/memoria.md` §10); no se carga en la base de datos |
| Catálogo de países | `frontend/public/datos/paises.geojson` (entregado, sin modificar) | no se regenera: usar la copia entregada |
| Registro de consultas al feed | tabla `ingest.extraction_log` | lo escribe el productor live en cada consulta |
| Registro de consultas del histórico | `data/raw/historico/manifest.json` | lo escribe la descarga del histórico |

## Procedencia y reutilización del histórico

`manifest.json` guarda, por cada consulta: URL completa, fecha de extracción, nº de registros que USGS anunció (`count`) y los recibidos, tamaño, SHA-256 y archivo. La descarga divide el año en meses; si un intervalo supera 20.000 resultados lo subdivide recursivamente en lugar de truncar (en 2025 con M ≥ 4 ningún mes se acerca: el mayor, julio, tiene 2.684). Es reutilizable: un mes cuyos archivos existen y coinciden con el SHA-256 registrado no se vuelve a pedir; si falta o se altera un archivo, solo se descarga ese mes. Un corte a mitad conserva los meses ya completos.

Resultado de la extracción realizada el 2026-11-17: **12 consultas, 18.302 eventos únicos, 0 duplicados entre intervalos, magnitud 4,0 a 8,8, 0 coordenadas inválidas**. Es una instantánea del catálogo en esa fecha, no un registro de todas sus revisiones pasadas. Si repites la descarga más adelante, el número puede variar porque USGS revisa su catálogo.

## Retención

- **Originales del feed live**: se conservan `RAW_RETENTION_DAYS` días (14 por defecto) y se podan en cada ciclo. El feed incluye `metadata.generated`, que cambia cada minuto aunque no haya novedades, así que la deduplicación usa el hash de las `features` y no el de los bytes: una respuesta con los mismos eventos que la última consulta correcta no se vuelve a guardar (en una prueba real, 3 consultas seguidas guardaron 1 original). La consulta sí queda registrada en `ingest.extraction_log` (`raw_path` nulo).
- **Registro de consultas** (`ingest.extraction_log`) y **datos procesados** (`event_message`, `event_current`, `quarantine_record`): no se borran. El histórico almacenado se mantiene aunque un evento deje de aparecer en la ventana de 24 h; que un evento salga del feed **no** implica que USGS lo haya eliminado.
- **Kafka**: 7 días o 1 GiB por partición (`compose.yaml`). Kafka es transporte, no archivo: la fuente de verdad es PostgreSQL.

## Recuperar un hueco mayor de 24 h

El feed solo contiene las últimas 24 horas. Si el productor live estuvo parado más tiempo, los eventos intermedios no se recuperan del feed: se obtienen con la API del catálogo para ese intervalo (`history_download --year`, o una consulta FDSN con las fechas del hueco) y se cargan como histórico. La reconciliación exhaustiva de eventos eliminados, fusionados o revisados fuera del feed es una ampliación fuera del alcance mínimo.

## Huella del catálogo de países

`ref.dim_country.source_sha256` guarda el SHA-256 del catálogo con saltos de línea normalizados a LF (`6866c877…c977f`, el publicado en `docs/curso/FUENTES-Y-LICENCIAS.md`). Con `core.autocrlf=true` en Windows la copia de trabajo tiene CRLF y el SHA del archivo en disco es otro (`d2aec98b…`); el contenido es el mismo.

## Permisos en Linux

El montaje `./data/raw` lo escribe el usuario `app` (uid 10001) del contenedor. En Linux, crea la carpeta con permisos de escritura para ese uid (`mkdir -p data/raw && chmod 777 data/raw`) antes de la primera ejecución. En Docker Desktop (Windows/macOS) no hace falta.
