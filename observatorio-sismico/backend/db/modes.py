"""Modos de ingesta y su esquema PostgreSQL (D2). Lista cerrada: nunca se interpola texto libre en SQL."""

# Esquemas con el mismo DDL de tablas de eventos. `historico` lo escribe el cargador del histórico (no Kafka).
MODE_SCHEMAS: tuple[str, ...] = ("demo", "live", "replay", "historico")
# Modos que pueden llegar por Kafka / consultarse con GET /api/eventos.
EVENT_MODES: tuple[str, ...] = ("demo", "live", "replay")


def schema_for_mode(mode: str) -> str:
    if mode not in MODE_SCHEMAS:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODE_SCHEMAS}")
    return mode
