"""Configuration read from environment variables, validated once per execution environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(RuntimeError):
    """A required setting is missing or invalid."""


@dataclass(frozen=True)
class Config:
    table_name: str
    service_name: str = "lambda-python-starter"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        table_name = env.get("TABLE_NAME", "").strip()
        if not table_name:
            raise ConfigError("TABLE_NAME environment variable is required")
        log_level = env.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        if log_level not in LOG_LEVELS:
            raise ConfigError(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}")
        service_name = env.get("SERVICE_NAME", "").strip() or cls.service_name
        return cls(table_name=table_name, service_name=service_name, log_level=log_level)


@lru_cache(maxsize=1)
def get_config() -> Config:
    """The process-wide configuration. Tests call ``get_config.cache_clear()`` after changing the environment."""
    return Config.from_env()
