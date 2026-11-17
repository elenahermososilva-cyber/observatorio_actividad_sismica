"""Migrador idempotente de PostgreSQL.

- Migración 001 = `backend/db/schema.sql`; las siguientes viven en `backend/db/migrations/NNN_*.sql`.
- Cada migración se aplica una sola vez (tabla `schema_migrations`) dentro de su transacción.
- Una migración cuya primera línea es `-- @per-schema` se ejecuta una vez por cada esquema de modo
  (demo, live, replay, historico) con `search_path` fijado a ese esquema, así el DDL se escribe sin calificar
  y queda idéntico en todos. Cualquier cambio posterior a las tablas de eventos debe ser una migración así.
- `pg_advisory_lock` serializa ejecuciones concurrentes (api y consumer arrancan a la vez).
- Se reintenta la conexión con espera progresiva: el healthcheck no garantiza aceptar conexiones de aplicación.
- Tras migrar se carga la dimensión país (`ref.dim_country`) desde COUNTRIES_GEOJSON, si el archivo existe.

Uso: python -m backend.db.migrate
"""

import hashlib
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from backend.common.backoff import retry_sync
from backend.common.config import database_url
from backend.common.logging_setup import configure_logging
from backend.db.modes import MODE_SCHEMAS

DB_DIR = Path(__file__).resolve().parent
BASE_SCHEMA = DB_DIR / "schema.sql"
MIGRATIONS_DIR = DB_DIR / "migrations"
ADVISORY_LOCK_KEY = 726_001  # arbitrario, fijo para todo el proyecto
PER_SCHEMA_MARKER = "-- @per-schema"
_MIGRATION_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")

log = logging.getLogger("migrate")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    @property
    def per_schema(self) -> bool:
        return self.sql.lstrip().startswith(PER_SCHEMA_MARKER)


def discover_migrations(
    base_schema: Path = BASE_SCHEMA,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> list[Migration]:
    """Devuelve las migraciones ordenadas; valida numeración única y sin huecos desde 002."""
    migrations = [Migration(1, "base_schema", base_schema)]
    if migrations_dir.is_dir():
        for path in sorted(migrations_dir.glob("*.sql")):
            match = _MIGRATION_NAME.match(path.name)
            if not match:
                raise ValueError(f"invalid migration file name: {path.name}")
            migrations.append(Migration(int(match.group(1)), path.stem, path))
    versions = [m.version for m in migrations]
    if len(set(versions)) != len(versions):
        raise ValueError(f"duplicate migration versions: {versions}")
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"migration versions must be consecutive from 001: {versions}")
    return migrations


def run_migrations(conninfo: str, upto: int | None = None) -> list[int]:
    """Aplica las migraciones pendientes (hasta `upto`, solo para pruebas). Devuelve las aplicadas ahora."""
    import psycopg
    from psycopg import sql

    applied_now: list[int] = []
    migrations = [m for m in discover_migrations() if upto is None or m.version <= upto]
    with psycopg.connect(conninfo, autocommit=True, connect_timeout=5) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS public.schema_migrations ("
                "version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                "checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            done = {
                row[0]: row[1]
                for row in conn.execute("SELECT version, checksum FROM public.schema_migrations")
            }
            for migration in migrations:
                if migration.version in done:
                    if done[migration.version] != migration.checksum:
                        raise RuntimeError(
                            f"migration {migration.version:03d} was modified after being applied; "
                            "create a new migration instead of editing it"
                        )
                    continue
                with conn.transaction():
                    if migration.per_schema:
                        for schema in MODE_SCHEMAS:
                            # SET LOCAL: vale solo dentro de esta transacción.
                            conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
                            conn.execute(migration.sql)
                        conn.execute("RESET search_path")  # el SET LOCAL seguiría vigente hasta el COMMIT
                    else:
                        conn.execute(migration.sql)
                    conn.execute(
                        "INSERT INTO public.schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                        (migration.version, migration.name, migration.checksum),
                    )
                label = migration.name if migration.version > 1 else f"001_{migration.name}"
                log.info("applied migration %s%s", label, " (per mode schema)" if migration.per_schema else "")
                applied_now.append(migration.version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
    return applied_now


def load_countries(conninfo: str, path: Path) -> tuple[int, int]:
    import psycopg

    from backend.db.countries import load_catalog

    with psycopg.connect(conninfo, autocommit=True, connect_timeout=5) as conn:
        return load_catalog(conn, path)


def main() -> int:
    configure_logging("migrate")
    import psycopg

    conninfo = database_url()
    applied = retry_sync(
        lambda: run_migrations(conninfo),
        retry_on=(psycopg.OperationalError,),
        attempts=20,
        maximum=10.0,
        description="database migration",
    )
    log.info("migrations up to date (applied now: %s)", applied or "none")

    catalog = Path(os.environ.get("COUNTRIES_GEOJSON", "/app/data/paises.geojson"))
    if catalog.is_file():
        retry_sync(
            lambda: load_countries(conninfo, catalog),
            retry_on=(psycopg.OperationalError,),
            attempts=5,
            description="country catalog load",
        )
    else:
        log.warning("country catalog not found at %s; ref.dim_country not loaded", catalog)
    return 0


if __name__ == "__main__":
    sys.exit(main())
