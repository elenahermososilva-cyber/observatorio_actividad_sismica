"""Cifras de la memoria (análisis, calidad antes/después y actualidad), calculadas sobre los datos reales.

Todas las cifras de la memoria salen de aquí: ninguna se escribe a mano. Es de solo lectura (no modifica la base ni los
archivos originales). Se ejecuta dentro de la imagen `api` (tiene psycopg y DATABASE_URL), montando los datos originales:

    docker compose run --rm --no-deps -v "${PWD}/scripts:/app/scripts" -v "${PWD}/data/raw:/app/data/raw:ro" \\
        -v "${PWD}/docs/evidencias:/app/docs/evidencias" api python scripts/memoria_datos.py

Escribe docs/evidencias/memoria-datos.json. Las cifras de `live` dependen del momento de ejecución: la memoria indica la
fecha de la instantánea (`generado_en`).
"""

import json
import math
import os
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

DB_URL = os.environ["DATABASE_URL"]
RAW = Path(os.environ.get("RAW_DATA_DIR", "/app/data/raw"))
OUT = Path(os.environ.get("EVIDENCE_DIR", "/app/docs/evidencias")) / "memoria-datos.json"
CHI2_CRITICAL_DF23_5PCT = 35.172  # valor crítico de chi² con 23 grados de libertad al 5 %
DAY_MS = 86_400_000


def q(conn, sql, *params):
    return conn.execute(sql, params).fetchall()


def one(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def pct(part, whole):
    return round(100.0 * part / whole, 2) if whole else None


def aki_utsu(mags, completeness, bin_width=0.1):
    """Estimador de máxima verosimilitud de b (Aki-Utsu) con corrección por magnitudes agrupadas."""
    sample = [m for m in mags if m >= completeness - 1e-9]
    if len(sample) < 30:
        return None
    mean = sum(sample) / len(sample)
    b = math.log10(math.e) / (mean - (completeness - bin_width / 2))
    return {"mc": completeness, "n": len(sample), "b": round(b, 3), "error_estandar": round(b / math.sqrt(len(sample)), 3)}


def analysis_history(conn):
    out = {}
    total = one(conn, "SELECT count(*) FROM historico.event_current")
    out["eventos"] = total
    out["rango_tiempo"] = [
        datetime.fromtimestamp(v / 1000, timezone.utc).isoformat()
        for v in q(conn, "SELECT min(time_ms), max(time_ms) FROM historico.event_current")[0]
    ]
    mags = [r[0] for r in q(conn, "SELECT mag FROM historico.event_current WHERE mag IS NOT NULL")]
    out["magnitud_con_valor"] = len(mags)
    out["recuento_mayor_o_igual"] = {
        str(m): sum(1 for x in mags if x >= m - 1e-9) for m in (4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0)
    }
    out["b_value_aki_utsu"] = [aki_utsu(mags, mc) for mc in (4.0, 4.5, 5.0)]
    out["magnitud_max"] = max(mags)
    out["magnitud_tipos"] = [{"tipo": t, "n": n} for t, n in q(
        conn, "SELECT coalesce(mag_type,'ND'), count(*) FROM historico.event_current GROUP BY 1 ORDER BY 2 DESC")]

    # --- ventanas diarias (365 días, con ceros) y valores extremos
    daily = {d: n for d, n in q(
        conn, "SELECT (time_ms - %s) / %s AS d, count(*) FROM historico.event_current "
              "WHERE time_ms >= %s AND time_ms < %s GROUP BY 1", 1735689600000, DAY_MS, 1735689600000, 1767225600000)}
    counts = [daily.get(i, 0) for i in range(365)]
    s = sorted(counts)
    q1, q3 = s[91], s[273]
    fence = q3 + 1.5 * (q3 - q1)
    outlier_days = [i for i, c in enumerate(counts) if c > fence]
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out["diario"] = {
        "dias": 365, "media": round(statistics.mean(counts), 2), "mediana": statistics.median(counts),
        "minimo": min(counts), "maximo": max(counts), "q1": q1, "q3": q3, "valla_tukey": round(fence, 1),
        "dias_atipicos": len(outlier_days),
        "eventos_en_dias_atipicos": sum(counts[i] for i in outlier_days),
        "media_sin_dias_atipicos": round(statistics.mean(c for i, c in enumerate(counts) if i not in outlier_days), 2),
        "dia_maximo": (base.fromtimestamp(base.timestamp() + counts.index(max(counts)) * 86400, timezone.utc)).date().isoformat(),
    }
    out["por_mes"] = [{"mes": m, "n": n} for m, n in q(
        conn, "SELECT to_char(to_timestamp(time_ms/1000) at time zone 'UTC','YYYY-MM'), count(*) "
              "FROM historico.event_current GROUP BY 1 ORDER BY 1")]

    # --- ciclo horario UTC: ¿hay una hora del día preferente?
    hours = [0] * 24
    for h, n in q(conn, "SELECT extract(hour from to_timestamp(time_ms/1000) at time zone 'UTC')::int, count(*) "
                        "FROM historico.event_current GROUP BY 1"):
        hours[h] = n
    expected = total / 24
    chi2 = sum((o - expected) ** 2 / expected for o in hours)
    out["horas_utc"] = {"por_hora": hours, "esperado_uniforme": round(expected, 1), "chi2": round(chi2, 1),
                        "critico_5pct_gl23": CHI2_CRITICAL_DF23_5PCT, "rechaza_uniformidad": chi2 > CHI2_CRITICAL_DF23_5PCT,
                        "cociente_max_min": round(max(hours) / min(hours), 2)}

    # --- profundidad
    out["profundidad"] = {
        "con_valor": one(conn, "SELECT count(depth_km) FROM historico.event_current"),
        "menos_70": one(conn, "SELECT count(*) FROM historico.event_current WHERE depth_km < 70"),
        "70_a_300": one(conn, "SELECT count(*) FROM historico.event_current WHERE depth_km >= 70 AND depth_km < 300"),
        "300_o_mas": one(conn, "SELECT count(*) FROM historico.event_current WHERE depth_km >= 300"),
        "maxima_km": one(conn, "SELECT max(depth_km) FROM historico.event_current"),
        "negativas": one(conn, "SELECT count(*) FROM historico.event_current WHERE depth_km < 0"),
    }
    # --- geografía
    out["pais"] = {
        "asignado": one(conn, "SELECT count(*) FROM historico.event_current WHERE country_status='assigned'"),
        "sin_pais": one(conn, "SELECT count(*) FROM historico.event_current WHERE country_status='unassigned'"),
        "pendiente": one(conn, "SELECT count(*) FROM historico.event_current WHERE country_status='pending'"),
    }
    out["top_paises"] = [{"pais": n, "n": c} for n, c in q(
        conn, "SELECT c.name_es, count(*) FROM historico.event_current e JOIN ref.dim_country c USING(country_id) "
              "GROUP BY 1 ORDER BY 2 DESC LIMIT 10")]
    out["top_subregiones"] = [{"subregion": n, "n": c} for n, c in q(
        conn, "SELECT c.subregion, count(*) FROM historico.event_current e JOIN ref.dim_country c USING(country_id) "
              "GROUP BY 1 ORDER BY 2 DESC LIMIT 8")]
    out["profundas_300_por_pais"] = [{"pais": n, "n": c} for n, c in q(
        conn, "SELECT coalesce(c.name_es,'Sin país asignado'), count(*) FROM historico.event_current e "
              "LEFT JOIN ref.dim_country c USING(country_id) WHERE depth_km >= 300 GROUP BY 1 ORDER BY 2 DESC LIMIT 5")]
    return out


def raw_history_stats():
    """Estado ANTES de la carga: los archivos originales del histórico, sin transformar."""
    manifest = json.loads((RAW / "historico" / "manifest.json").read_text(encoding="utf-8"))
    received = sum(qr["features_received"] for m in manifest["months"].values() for qr in m["queries"])
    queries = sum(len(m["queries"]) for m in manifest["months"].values())
    ids, features = set(), 0
    stats = {"mag_nula": 0, "magtype_nulo": 0, "place_nulo_o_vacio": 0, "place_con_espacios": 0, "depth_nula": 0,
             "depth_negativa": 0, "mag_negativa": 0, "tipo_distinto": 0, "coord_invalida": 0, "no_point": 0,
             "updated_antes_de_time": 0, "magtype_mayusculas": 0}
    for path in sorted((RAW / "historico").glob("*.geojson")):
        for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
            features += 1
            ids.add(f.get("id"))
            p, g = f.get("properties") or {}, f.get("geometry") or {}
            stats["mag_nula"] += p.get("mag") is None
            stats["magtype_nulo"] += not p.get("magType")
            place = p.get("place")
            stats["place_nulo_o_vacio"] += not (isinstance(place, str) and place.strip())
            stats["place_con_espacios"] += isinstance(place, str) and place != place.strip()
            stats["magtype_mayusculas"] += isinstance(p.get("magType"), str) and p["magType"] != p["magType"].lower()
            stats["tipo_distinto"] += p.get("type") != "earthquake"
            stats["no_point"] += g.get("type") != "Point"
            c = g.get("coordinates") or []
            ok = len(c) >= 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in c[:2]) \
                and -180 <= c[0] <= 180 and -90 <= c[1] <= 90
            stats["coord_invalida"] += not ok
            d = c[2] if len(c) > 2 else None
            stats["depth_nula"] += d is None
            stats["depth_negativa"] += isinstance(d, (int, float)) and d < 0
            stats["mag_negativa"] += isinstance(p.get("mag"), (int, float)) and p["mag"] < 0
            stats["updated_antes_de_time"] += (p.get("updated") or 0) < (p.get("time") or 0)
    return {"consultas": queries, "features_recibidas_suma": received, "features_leidas": features,
            "ids_unicos": len(ids), "duplicados_entre_intervalos": features - len(ids), **stats}


def quality_history_after(conn):
    flags = {c: n for c, n in q(conn, "SELECT code, count(*) FROM historico.event_current, unnest(quality_flags) code GROUP BY 1")}
    return {
        "filas_event_current": one(conn, "SELECT count(*) FROM historico.event_current"),
        "filas_event_message": one(conn, "SELECT count(*) FROM historico.event_message"),
        "cuarentena": one(conn, "SELECT count(*) FROM historico.quarantine_record"),
        "mag_nula": one(conn, "SELECT count(*) FROM historico.event_current WHERE mag IS NULL"),
        "mag_cero": one(conn, "SELECT count(*) FROM historico.event_current WHERE mag = 0"),
        "depth_nula": one(conn, "SELECT count(*) FROM historico.event_current WHERE depth_km IS NULL"),
        "sin_aviso": one(conn, "SELECT count(*) FROM historico.event_current WHERE cardinality(quality_flags) = 0"),
        "no_evaluados": one(conn, "SELECT count(*) FROM historico.event_current WHERE quality_flags IS NULL"),
        "avisos": flags,
        "claves_unicas_event_id": one(conn, "SELECT count(DISTINCT event_id) FROM historico.event_current"),
    }


def live_stats(conn):
    out = {}
    out["eventos_actuales"] = one(conn, "SELECT count(*) FROM live.event_current")
    out["mensajes_aceptados"] = one(conn, "SELECT count(*) FROM live.event_message")
    out["eventos_con_revision"] = one(conn, "SELECT count(*) FROM (SELECT event_id FROM live.event_message GROUP BY 1 HAVING count(*) > 1) t")
    out["revisiones"] = out["mensajes_aceptados"] - out["eventos_actuales"]
    out["rango_tiempo_eventos"] = [
        datetime.fromtimestamp(v / 1000, timezone.utc).isoformat()
        for v in q(conn, "SELECT min(time_ms), max(time_ms) FROM live.event_current")[0]
    ]
    out["cuarentena"] = [{"motivo": r, "n": n} for r, n in q(
        conn, "SELECT left(reason, strpos(reason, ':') - 1) || ' (' || coalesce(substring(reason from $$type='([^']*)'$$), '-') || ')', count(*) "
              "FROM live.quarantine_record GROUP BY 1 ORDER BY 2 DESC")]
    out["mag_nula"] = one(conn, "SELECT count(*) FROM live.event_current WHERE mag IS NULL")
    out["mag_negativa"] = one(conn, "SELECT count(*) FROM live.event_current WHERE mag < 0")
    out["sin_pais"] = one(conn, "SELECT count(*) FROM live.event_current WHERE country_status='unassigned'")
    out["tipos_magnitud"] = [{"tipo": t, "n": n} for t, n in q(
        conn, "SELECT coalesce(mag_type,'ND'), count(*) FROM live.event_current GROUP BY 1 ORDER BY 2 DESC LIMIT 6")]

    # --- registro de consultas a USGS y deduplicación del feed (cada respuesta repite las 24 h completas)
    ext = q(conn, "SELECT ok, count(*), coalesce(sum(record_count),0), avg(latency_ms), "
                  "percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), max(latency_ms), min(started_at), max(started_at) "
                  "FROM ingest.extraction_log WHERE mode='live' GROUP BY 1")
    out["consultas"] = {("ok" if r[0] else "fallidas"): {
        "n": r[1], "features_suma": int(r[2]), "latencia_media_ms": None if r[3] is None else round(float(r[3]), 1),
        "latencia_p95_ms": None if r[4] is None else round(float(r[4]), 1), "latencia_max_ms": r[5],
        "primera": r[6].isoformat(), "ultima": r[7].isoformat()} for r in ext}
    appearances = out["consultas"].get("ok", {}).get("features_suma", 0)
    out["deduplicacion_del_feed"] = {
        "apariciones_de_features_en_respuestas": appearances, "versiones_publicadas": out["mensajes_aceptados"] + sum(c["n"] for c in out["cuarentena"]),
        "porcentaje_suprimido": pct(appearances - out["mensajes_aceptados"] - sum(c["n"] for c in out["cuarentena"]), appearances),
    }
    out["originales_guardados"] = {
        "archivos_distintos": one(conn, "SELECT count(DISTINCT raw_path) FROM ingest.extraction_log WHERE raw_path IS NOT NULL"),
        "respuestas_sin_copia_por_ser_identicas": one(conn, "SELECT count(*) FROM ingest.extraction_log WHERE ok AND raw_path IS NULL"),
    }

    # --- actualidad: retrasos de publicación de USGS y de nuestra ingesta
    # Se excluye el ciclo de arranque de cada sesión del productor: publica de golpe las 24 h anteriores, así que (i) el
    # retraso de ingesta sería artificial y (ii) la primera versión vista puede ser ya una revisión posterior a la primera
    # publicación de USGS. Fuera de esos ciclos se consulta cada 60 s, y `updated` de la primera versión vista ≈ su publicación.
    starts = [r[0] for r in q(conn, "SELECT started_at FROM (SELECT started_at, started_at - lag(started_at) OVER (ORDER BY started_at) AS gap "
                                    "FROM ingest.extraction_log WHERE mode='live' AND ok) t WHERE gap IS NULL OR gap > interval '5 minutes'")]
    not_startup = " AND ".join(["NOT (ingested_at >= %s AND ingested_at < %s + interval '2 minutes')"] * len(starts)) or "TRUE"
    sparams = [x for s_ in starts for x in (s_, s_)]

    def delay(where_mag, only_normal):
        extra = f" AND {not_startup}" if only_normal else ""
        row = q(conn, "WITH first_version AS (SELECT DISTINCT ON (event_id) event_id, updated_ms, ingested_at, "
                      "(payload->'properties'->>'time')::bigint AS t, (payload->'properties'->>'mag')::float AS mag "
                      "FROM live.event_message ORDER BY event_id, updated_ms) "
                      "SELECT count(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY (updated_ms - t) / 60000.0), "
                      "percentile_cont(0.95) WITHIN GROUP (ORDER BY (updated_ms - t) / 60000.0), max((updated_ms - t) / 60000.0) "
                      f"FROM first_version WHERE {where_mag}{extra}", *(sparams if only_normal else []))[0]
        if not row[0]:
            return {"n": 0}
        return {"n": row[0], "mediana": round(float(row[1]), 1), "p95": round(float(row[2]), 1), "max": round(float(row[3]), 1)}

    out["actualidad"] = {
        "nota": "minutos entre la ocurrencia y la primera versión publicada (updated de la primera versión vista)",
        "publicacion_usgs_min_todos_incluye_arranque": delay("TRUE", False),
        "publicacion_usgs_min_fuera_de_arranque_todos": delay("TRUE", True),
        "publicacion_usgs_min_fuera_de_arranque_M4": delay("mag >= 4", True),
        "publicacion_usgs_min_fuera_de_arranque_menor_M4": delay("mag < 4", True),
    }
    row = q(conn, f"SELECT count(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch from ingested_at) - updated_ms / 1000.0), "
                  f"percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch from ingested_at) - updated_ms / 1000.0), "
                  f"max(extract(epoch from ingested_at) - updated_ms / 1000.0) FROM live.event_message WHERE {not_startup}", *sparams)[0]
    out["actualidad"]["ingesta_tras_actualizacion_usgs_s"] = {
        "n": row[0], "mediana": None if row[1] is None else round(float(row[1]), 1),
        "p95": None if row[2] is None else round(float(row[2]), 1), "max": None if row[3] is None else round(float(row[3]), 1),
        "ciclos_de_arranque_excluidos": len(starts)}

    # --- revisiones: qué cambió entre versiones consecutivas
    rows = q(conn, "WITH v AS (SELECT event_id, updated_ms, (payload->'properties'->>'mag')::float AS mag, "
                   "payload->'geometry'->'coordinates' AS coords, (payload->'properties'->>'time')::bigint AS t, "
                   "lag((payload->'properties'->>'mag')::float) OVER w AS pmag, lag(payload->'geometry'->'coordinates') OVER w AS pcoords, "
                   "lag((payload->'properties'->>'time')::bigint) OVER w AS pt, lag(updated_ms) OVER w AS pu "
                   "FROM live.event_message WINDOW w AS (PARTITION BY event_id ORDER BY updated_ms)) "
                   "SELECT count(*), count(*) FILTER (WHERE mag IS DISTINCT FROM pmag), count(*) FILTER (WHERE coords IS DISTINCT FROM pcoords), "
                   "count(*) FILTER (WHERE t IS DISTINCT FROM pt), max(abs(mag - pmag)), percentile_cont(0.5) WITHIN GROUP (ORDER BY (updated_ms - pu)/60000.0) "
                   "FROM v WHERE pu IS NOT NULL")[0]
    out["revisiones_detalle"] = {"versiones_con_anterior": rows[0], "cambia_magnitud": rows[1], "cambia_ubicacion": rows[2],
                                 "cambia_tiempo": rows[3], "max_cambio_magnitud": None if rows[4] is None else round(float(rows[4]), 2),
                                 "mediana_minutos_entre_versiones": None if rows[5] is None else round(float(rows[5]), 1)}
    out["secuencia_revisiones_no_monotona"] = one(
        conn, "SELECT count(*) FROM live.event_current c JOIN live.event_message m ON m.message_id = c.message_id "
              "WHERE c.current_version_ms <> (SELECT max(updated_ms) FROM live.event_message WHERE event_id = c.event_id)")
    return out


def consistency(conn):
    return {
        "event_current_sin_mensaje_origen": one(conn, "SELECT count(*) FROM live.event_current c LEFT JOIN live.event_message m "
                                                      "ON m.message_id = c.message_id AND m.event_id = c.event_id AND m.updated_ms = c.current_version_ms WHERE m.message_id IS NULL"),
        "paises_inexistentes_en_catalogo": one(conn, "SELECT count(*) FROM historico.event_current c LEFT JOIN ref.dim_country d USING(country_id) "
                                                     "WHERE c.country_id IS NOT NULL AND d.country_id IS NULL"),
        "catalogo_paises": one(conn, "SELECT count(*) FROM ref.dim_country"),
        "catalogo_ADM0_A3_distintos": one(conn, "SELECT count(DISTINCT country_id) FROM ref.dim_country"),
        "historico_tiempo_en_2025": one(conn, "SELECT count(*) FROM historico.event_current WHERE time_ms >= 1735689600000 AND time_ms < 1767225600000"),
    }


def live_equivalent_sample(conn):
    """Muestra live EQUIVALENTE al histórico: mismo umbral (M >= 4) y solo días UTC completos con cobertura del feed.

    El histórico solo contiene M >= 4; comparar con todo el feed (que incluye M < 4) mezclaría poblaciones distintas.
    El primer día con cobertura completa es el siguiente al día del primer ciclo (el feed cubre las 24 h anteriores).
    """
    first = one(conn, "SELECT min(started_at) FROM ingest.extraction_log WHERE mode='live' AND ok")
    first_day = (first.astimezone(timezone.utc) + timedelta(days=0)).date()  # el primer ciclo ya cubre las 24 h anteriores
    today = datetime.now(timezone.utc).date()
    days = []
    d = first_day
    while d < today:
        start = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
        end = start + DAY_MS
        row = q(conn, "SELECT count(*), count(*) FILTER (WHERE country_status='unassigned'), count(*) FILTER (WHERE depth_km < 70), "
                      "count(*) FILTER (WHERE depth_km >= 300), count(*) FILTER (WHERE mag_type IN ('mb','mww','mwr','mw','mwb')), "
                      "min(mag), max(mag) FROM live.event_current WHERE time_ms >= %s AND time_ms < %s AND mag >= 4", start, end)[0]
        days.append({"dia": d.isoformat(), "eventos_M4": row[0], "sin_pais": row[1], "menos_70_km": row[2], "mas_300_km": row[3],
                     "mag_max": row[6]})
        d += timedelta(days=1)
    total = sum(x["eventos_M4"] for x in days)
    hist = q(conn, "SELECT count(*), count(*) FILTER (WHERE country_status='unassigned'), count(*) FILTER (WHERE depth_km < 70), "
                   "count(*) FILTER (WHERE depth_km >= 300) FROM historico.event_current")[0]
    return {
        "filtro": "mag >= 4, tiempo de ocurrencia en días UTC completos desde el primer ciclo live",
        "dias": days, "dias_n": len(days), "eventos_M4_total": total,
        "media_por_dia_live": round(total / len(days), 2) if days else None,
        "porcentaje_sin_pais_live": pct(sum(x["sin_pais"] for x in days), total),
        "porcentaje_menos_70_km_live": pct(sum(x["menos_70_km"] for x in days), total),
        "porcentaje_mas_300_km_live": pct(sum(x["mas_300_km"] for x in days), total),
        "historico_2025": {"eventos": hist[0], "porcentaje_sin_pais": pct(hist[1], hist[0]),
                           "porcentaje_menos_70_km": pct(hist[2], hist[0]), "porcentaje_mas_300_km": pct(hist[3], hist[0])},
    }


def coverage_gaps(conn):
    """Huecos de la ingesta live (más de 5 min entre consultas correctas) y si cabían en la ventana de 24 h del feed."""
    rows = q(conn, "SELECT prev, started_at, started_at - prev FROM (SELECT started_at, lag(started_at) OVER (ORDER BY started_at) AS prev "
                   "FROM ingest.extraction_log WHERE mode='live' AND ok) t WHERE started_at - prev > interval '5 minutes' ORDER BY prev")
    return [{"desde": a.isoformat(timespec="seconds"), "hasta": b.isoformat(timespec="seconds"),
             "horas": round(g.total_seconds() / 3600, 2), "recuperable_con_el_feed_24h": g.total_seconds() < 24 * 3600} for a, b, g in rows]


def main() -> None:
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = on")
        data = {
            "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "analisis_historico_2025": analysis_history(conn),
            "calidad": {"antes_historico_original": raw_history_stats(), "despues_historico_en_base": quality_history_after(conn),
                        "consistencia": consistency(conn)},
            "live": live_stats(conn),
            "live_muestra_equivalente": live_equivalent_sample(conn),
            "huecos_de_ingesta_live": coverage_gaps(conn),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(data, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
