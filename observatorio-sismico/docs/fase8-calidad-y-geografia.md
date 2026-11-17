# Calidad y atribución geográfica: reglas, decisiones y resultados medidos

Material de partida para el apartado de calidad de la memoria (enunciado §6 y §7). Los números proceden de la carga real del histórico 2025 (M ≥ 4, mundo, 18.302 eventos) realizada el 2026-11-17; todas las consultas son reproducibles.

## 1. Qué se rechaza y qué solo se señala

| Situación | Tratamiento | Dónde queda |
|---|---|---|
| JSON ilegible, esquema inválido, coordenadas no finitas o fuera de rango, geometría que no es Point | **Cuarentena** con motivo (`invalid_json`, `schema_violation`, `invalid_coordinates`) | `quarantine_record` (payload original + referencia) |
| `properties.type` distinto de `earthquake` (explosiones, voladuras…) | **Cuarentena** `non_earthquake_type`, con el tipo en el detalle | `quarantine_record` |
| Mensaje de un modo en el topic de otro | **Cuarentena** `mode_mismatch` | `quarantine_record` del esquema del topic |
| Magnitud o profundidad ausentes | Se conserva `NULL` (se muestra «ND»). **Nunca se rellena con 0** | `quality_flags`: `gap_mag_missing`, `gap_depth_missing` |
| Magnitud o profundidad **negativas** | Válidas: se conservan y se señalan (no son errores automáticos) | `anomaly_mag_negative`, `anomaly_depth_negative` |
| Valores físicamente sospechosos (M fuera de [-2, 10], profundidad > 800 km, evento «en el futuro», actualización anterior a la ocurrencia) | Se conservan y se señalan | `anomaly_*` |
| Espacios sobrantes en `place`, `place` vacío, `magType` en mayúsculas | **Transformación** que cambia el dato, registrada | `fixed_*` |
| Epicentro fuera de todo polígono | **Sin país asignado**: se conserva y permanece en el análisis | `country_status = 'unassigned'` |

El original nunca se modifica: `event_message.payload` conserva el Feature exactamente como llegó; las transformaciones solo afectan a las columnas derivadas de `event_current`. Los códigos están documentados en `backend/consumer/quality.py` (`FLAG_CODES`).

## 2. Regla de atribución de país

Punto-en-polígono sobre Natural Earth 1:110M (`backend/consumer/geo.py`), WGS84, sin reproyectar.

1. **Solo geometría.** El texto `place` y la proximidad nunca deciden el país.
2. **Frontera:** predicado `covered_by`; un punto sobre el borde cuenta como dentro.
3. **Varias coincidencias** (vértice compartido, solape): gana el menor `ADM0_A3` alfabético (determinista) y se registra `country_boundary_ambiguous`. Ejemplo real: el vértice España-Francia `(-1.901351, 43.422802)` devuelve `ESP`.
4. **Antimeridiano:** el catálogo parte los polígonos en ±180°; `lon = 180` y `lon = -180` caen cada uno en su pieza (verificado con Rusia y Fiyi).
5. **Geometrías inválidas:** 2 de las 177 (USA y SDN) tienen autointersecciones. Se reparan con `make_valid` (el área no cambia: 1122,28 y 156,44).
6. **Limitación declarada:** las costas están simplificadas y faltan islas menores (Taveuni, en Fiyi, queda sin país).

## 3. Resultados sobre el histórico 2025

Carga: 18.302 eventos `NEW`, 0 rechazos, 81 s (225 eventos/s incluyendo escritura transaccional). Recarga: 18.302 `DUPLICATE`, 0 cambios.

| Estado | Eventos | % |
|---|---|---|
| Con país (`assigned`) | 3.952 | 21,6 |
| Sin país asignado (`unassigned`) | 14.350 | 78,4 |

Países con más eventos: China 354, Chile 348, Indonesia 306, Etiopía 265, Argentina 236.

Avisos de calidad: **18.299 de 18.302 registros sin ningún aviso**; solo `fixed_place_trimmed` en 3 (0,02 %). Un catálogo oficial ya curado deja poco que limpiar: esto es un resultado, no una ausencia de análisis. En el feed live (227 eventos) aparecieron 2 magnitudes negativas válidas y 2 explosiones, que fueron a cuarentena.

### ¿Por qué el 78 % queda sin país? Contraste independiente

La mayoría de los terremotos M ≥ 4 ocurren en el mar (zonas de subducción y dorsales). Para comprobar que no es un fallo se contrastó con el texto `place` **solo como verificación, nunca como fuente**:

- 13.423 eventos tienen un `place` que termina en un país del catálogo; la atribución geométrica coincide en 3.351 (25 %) y deja 9.833 sin país.
- Esos 9.833 están a una **mediana de 105 km** de la costa del país que nombra el texto: 10,7 % a menos de 25 km, 22,3 % a menos de 50 km, 34,2 % entre 100 y 200 km, 3,4 % a más de 500 km. Son epicentros realmente en el mar con `place` del estilo «90 km W de Valparaíso, Chile». Solo la franja de menos de ~25-50 km podría deberse a la simplificación de costa.
- 239 eventos se asignaron a un país distinto del que nombra el texto, casi todos fronteras: 56 en China con `place` de Nepal, 32 en Bolivia con `place` de Chile, 24 en Myanmar con `place` de India. El epicentro está en un país y la ciudad de referencia en el vecino.

Atribuir por el texto habría colocado unos 9.800 eventos marítimos dentro de países que no los contienen y habría movido otros 239 al país equivocado. Y atribuir al «más cercano» tampoco es correcto: el enunciado lo prohíbe expresamente.

## 4. Consultas para reproducir las cifras

```sql
-- estado de la atribución
SELECT country_status, count(*), round(100.0*count(*)/sum(count(*)) OVER (),1) FROM historico.event_current GROUP BY 1;

-- cuántos registros afecta cada regla de calidad
SELECT code, count(*) FROM historico.event_current, unnest(quality_flags) code GROUP BY 1 ORDER BY 2 DESC;

-- registros sin ningún aviso
SELECT count(*) FROM historico.event_current WHERE cardinality(quality_flags) = 0;

-- rechazos y su motivo
SELECT left(reason, strpos(reason, ':') - 1) AS motivo, count(*) FROM live.quarantine_record GROUP BY 1;
```

## 5. Cómo se ejecuta

```bash
# 1) descargar el histórico (una vez)  2) cargarlo con el mismo procesamiento que el consumidor
docker compose run --rm --no-deps producer python -m backend.producer.history_download
docker compose run --rm --no-deps consumer python -m backend.consumer.history_loader
# evaluar a posteriori eventos sin país/calidad (también se hace solo al arrancar el consumidor)
docker compose run --rm --no-deps consumer python -m backend.consumer.geo_backfill
```
