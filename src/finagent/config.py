"""Typed settings: secrets from .env, everything else from configs/base.yaml."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str = "postgresql://finagent:finagent@localhost:5432/finagent"


class Provider(BaseModel):
    base_url: str
    api_key_env: str


class ModelSpec(BaseModel):
    provider: str
    model: str
    price_in: float  # USD per million input tokens
    price_out: float  # USD per million output tokens


class LLMConfig(BaseModel):
    default: str
    judge: str
    cache_dir: str
    providers: dict[str, Provider]
    models: dict[str, ModelSpec]


class Config(BaseModel):
    llm: LLMConfig


@lru_cache
def env() -> Env:
    return Env()


@lru_cache
def load_config(path: Path = ROOT / "configs" / "base.yaml") -> Config:
    with open(path) as f:
        return Config.model_validate(yaml.safe_load(f))


def secret(name: str) -> str:
    """Read a secret from the process env, falling back to .env."""
    if name in os.environ:
        return os.environ[name]
    from dotenv import dotenv_values  # installed with pydantic-settings

    value: Any = dotenv_values(ROOT / ".env").get(name)
    if not value:
        raise RuntimeError(f"{name} is not set; add it to .env")
    return str(value)
