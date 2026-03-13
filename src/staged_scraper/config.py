from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import ScraperConfig


class ConfigError(RuntimeError):
    pass


DEFAULT_CONFIG = ScraperConfig()



def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> ScraperConfig:
    config = DEFAULT_CONFIG.model_copy(deep=True)
    if path is not None:
        if not path.exists():
            raise ConfigError(f"Config file does not exist: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ConfigError("Config file must contain a mapping at the top level")
        try:
            config = ScraperConfig.model_validate({**config.model_dump(mode="python"), **raw})
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc
    if overrides:
        merged = config.model_dump(mode="python")
        _deep_merge(merged, overrides)
        try:
            config = ScraperConfig.model_validate(merged)
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc
    return config



def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
