"""Modos de ingesta y su esquema PostgreSQL (D2). Listas cerradas: nunca se interpola texto libre en SQL."""

# Esquemas con el mismo DDL de tablas de eventos.
MODE_SCHEMAS: tuple[str, ...] = ("demo", "live", "replay", "historico")
# Modos que pueden llegar por Kafka / consultarse con GET /api/eventos.
EVENT_MODES: tuple[str, ...] = ("demo", "live", "replay")
# Modos que la API puede LEER: los anteriores más el histórico 2025 (solo lectura; nunca llega por Kafka).
READ_MODES: tuple[str, ...] = EVENT_MODES + ("historico",)
# Cada modo de mensaje escribe en exactamente un esquema. `historical` no pasa por Kafka: lo carga history_loader.
MODE_TO_SCHEMA: dict[str, str] = {"demo": "demo", "live": "live", "replay": "replay", "historical": "historico"}


def schema_for_read_mode(mode: str) -> str:
    """Esquema que consulta la API para un modo de lectura (lista cerrada)."""
    if mode not in READ_MODES:
        raise ValueError(f"unknown read mode {mode!r}; expected one of {READ_MODES}")
    return "historico" if mode == "historico" else schema_for_mode(mode)


def schema_for_mode(mode: str) -> str:
    try:
        return MODE_TO_SCHEMA[mode]
    except (KeyError, TypeError):
        raise ValueError(f"unknown mode {mode!r}; expected one of {tuple(MODE_TO_SCHEMA)}") from None
