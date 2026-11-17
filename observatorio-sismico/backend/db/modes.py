"""Modos de ingesta y su esquema PostgreSQL (D2). Listas cerradas: nunca se interpola texto libre en SQL."""

# Esquemas con el mismo DDL de tablas de eventos.
MODE_SCHEMAS: tuple[str, ...] = ("demo", "live", "replay", "historico")
# Modos que pueden llegar por Kafka / consultarse con GET /api/eventos.
EVENT_MODES: tuple[str, ...] = ("demo", "live", "replay")
# Cada modo de mensaje escribe en exactamente un esquema. `historical` no pasa por Kafka: lo carga history_loader.
MODE_TO_SCHEMA: dict[str, str] = {"demo": "demo", "live": "live", "replay": "replay", "historical": "historico"}


def schema_for_mode(mode: str) -> str:
    try:
        return MODE_TO_SCHEMA[mode]
    except (KeyError, TypeError):
        raise ValueError(f"unknown mode {mode!r}; expected one of {tuple(MODE_TO_SCHEMA)}") from None
