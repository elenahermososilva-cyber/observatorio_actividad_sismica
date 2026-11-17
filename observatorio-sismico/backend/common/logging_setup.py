"""Logging uniforme en UTC para todos los servicios."""

import logging
import os
import time


class _UtcFormatter(logging.Formatter):
    converter = time.gmtime


def configure_logging(service: str, level: str | None = None) -> logging.Logger:
    level_name = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler()
    handler.setFormatter(
        _UtcFormatter(
            fmt=f"%(asctime)sZ %(levelname)s {service} %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level_name, logging.INFO))
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(root.level, logging.WARNING))
    return logging.getLogger(service)
