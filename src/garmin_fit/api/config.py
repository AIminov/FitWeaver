"""Load api_config.yaml into a small settings object.

Separate from bot_config.yaml on purpose: bot_config.yaml describes the
bot's own local LLM connection choice (or, post-refactor, which API it
calls); api_config.yaml describes the API server's own identity -- which
LLM *it* proxies to, its bind address, and its own shared secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import yaml

from ..config import API_CONFIG_FILE


@dataclass
class ApiSettings:
    api_token: str
    host: str = "0.0.0.0"
    port: int = 8008
    llm_url: str = "http://192.168.1.107:8080/v1"
    llm_model: str = "/home/amir/.lmstudio/models/unsloth/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-IQ3_XXS.gguf"
    llm_api_type: str = "openai"
    llm_timeout_sec: int = 900
    rate_limit_per_minute: float = 6.0
    rate_limit_burst: float = 2.0


def load_api_settings() -> ApiSettings:
    if not API_CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"api_config.yaml not found at {API_CONFIG_FILE}\n"
            "Copy api_config.yaml.example to api_config.yaml and fill in your values."
        )

    with open(API_CONFIG_FILE, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    api_token = os.environ.get("FITWEAVER_API_TOKEN") or raw.get("api_token")
    if not api_token or api_token == "REPLACE_WITH_A_LONG_RANDOM_SECRET":
        raise ValueError(
            "api_token is not configured -- set it in api_config.yaml or the "
            "FITWEAVER_API_TOKEN environment variable."
        )

    return ApiSettings(
        api_token=str(api_token),
        host=str(raw.get("host", "0.0.0.0")),
        port=int(raw.get("port", 8008)),
        llm_url=str(raw.get("llm_url", "http://192.168.1.107:8080/v1")),
        llm_model=str(raw.get("llm_model", "/home/amir/.lmstudio/models/unsloth/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-IQ3_XXS.gguf")),
        llm_api_type=str(raw.get("llm_api_type", "openai")),
        llm_timeout_sec=int(raw.get("llm_timeout_sec", 900)),
        rate_limit_per_minute=float(raw.get("rate_limit_per_minute", 6.0)),
        rate_limit_burst=float(raw.get("rate_limit_burst", 2.0)),
    )
