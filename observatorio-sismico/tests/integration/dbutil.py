"""Base de datos temporal migrada con el migrador REAL, para tests de integración con PostgreSQL.

Se ejecuta dentro del contenedor (donde existe DATABASE_URL y psycopg). Cada módulo crea su propia base
(`CREATE DATABASE t_xxx`), aplica todas las migraciones y carga ref.dim_country; al terminar la elimina.
En el host, sin psycopg o sin base accesible, los tests se omiten.
"""

import os
import unittest
import uuid
from pathlib import Path

try:
    import psycopg
    from psycopg.conninfo import make_conninfo

    from backend.db.migrate import load_countries, run_migrations
    from backend.db.modes import MODE_SCHEMAS

    AVAILABLE = True
except ImportError:
    AVAILABLE = False

DATABASE_URL = os.environ.get("DATABASE_URL")
COUNTRIES = next(
    path
    for path in (
        Path(os.environ["COUNTRIES_GEOJSON"]) if os.environ.get("COUNTRIES_GEOJSON") else None,
        Path(__file__).resolve().parents[2] / "frontend" / "public" / "datos" / "paises.geojson",
    )
    if path is not None and path.is_file()
)


class TempDatabase:
    def __init__(self) -> None:
        self.name = f"t_{uuid.uuid4().hex[:12]}"
        self.conninfo = ""

    def create(self, load_catalog: bool = True, upto: int | None = None) -> None:
        if not AVAILABLE:
            raise unittest.SkipTest("dependencias del backend no disponibles")
        if not DATABASE_URL:
            raise unittest.SkipTest("DATABASE_URL no definida")
        try:
            with psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=3) as admin:
                admin.execute(f'CREATE DATABASE "{self.name}"')
        except psycopg.OperationalError as error:
            raise unittest.SkipTest(f"base no accesible: {error}") from error
        self.conninfo = make_conninfo(DATABASE_URL, dbname=self.name)
        run_migrations(self.conninfo, upto=upto)
        if load_catalog and upto is None:
            load_countries(self.conninfo, COUNTRIES)

    def drop(self) -> None:
        if not self.conninfo:
            return
        with psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=3) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)')

    def truncate_events(self) -> None:
        """Vacía las tablas de eventos de todos los esquemas de modo (el catálogo de países se conserva)."""
        with psycopg.connect(self.conninfo, autocommit=True) as conn:
            for schema in MODE_SCHEMAS:
                conn.execute(
                    f'TRUNCATE "{schema}".event_current, "{schema}".event_message, "{schema}".quarantine_record '
                    "RESTART IDENTITY"
                )
