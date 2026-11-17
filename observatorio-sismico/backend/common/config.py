"""Lectura de configuración desde variables de entorno (sin valores secretos por defecto)."""

import os
from collections.abc import Mapping


class ConfigError(ValueError):
    pass


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def get_str(name: str, default: str | None = None, env: Mapping[str, str] | None = None) -> str:
    value = _env(env).get(name)
    if value is None or value.strip() == "":
        if default is None:
            raise ConfigError(f"missing required environment variable {name}")
        return default
    return value.strip()


def get_int(
    name: str,
    default: int | None = None,
    *,
    minimum: int | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    raw = get_str(name, None if default is None else str(default), env)
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from error
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


def get_list(
    name: str,
    default: str = "",
    env: Mapping[str, str] | None = None,
) -> list[str]:
    raw = _env(env).get(name)
    if raw is None or raw.strip() == "":
        raw = default
    return [item.strip() for item in raw.split(",") if item.strip()]


def database_url(env: Mapping[str, str] | None = None) -> str:
    return get_str("DATABASE_URL", env=env)
