"""P11 settings, loaded from ``~/.config/p11/config.toml`` and ``P11_`` environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from p11 import paths

LOOPBACK_HOSTS = frozenset({"127.0.0.1"})


class Settings(BaseSettings):
    """User settings. The Studio host is fixed to loopback in v1 (spec S1)."""

    model_config = SettingsConfigDict(env_prefix="P11_", extra="ignore")

    host: str = "127.0.0.1"
    studio_port: int = Field(default=8111, ge=1024, le=65535)
    engine_port: int = Field(default=8188, ge=1024, le=65535)
    models_root: Path = Field(default_factory=lambda: paths.resolve().models)
    outputs_root: Path = Field(default_factory=lambda: paths.resolve().pictures)
    # Thermal guard thresholds (owner question 5, spec H9; Phase 13 may tune them by ±5 °C).
    thermal_pause_c: int = Field(default=87, ge=50, le=100)
    thermal_resume_c: int = Field(default=80, ge=40, le=95)
    # Video limits (R13): beyond these an upload is accepted with a warning.
    video_warn_seconds: float = Field(default=60.0, gt=0, le=600)
    video_warn_height: int = Field(default=1080, ge=240, le=2160)
    # Seconds without jobs before the Studio stops the engine and frees the GPU lock (R24).
    engine_idle_stop: float = Field(default=300.0, ge=10, le=86400)

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        if value not in LOOPBACK_HOSTS:
            raise ValueError("host must be 127.0.0.1: P11 Studio is local-only (spec S1)")
        return value

    @model_validator(mode="after")
    def _thermal_hysteresis(self) -> Settings:
        if self.thermal_resume_c >= self.thermal_pause_c:
            raise ValueError("thermal_resume_c must be below thermal_pause_c")
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml = TomlConfigSettingsSource(settings_cls, toml_file=paths.config_file())
        return (init_settings, env_settings, toml)


def load_settings(**overrides: Any) -> Settings:
    return Settings(**overrides)
