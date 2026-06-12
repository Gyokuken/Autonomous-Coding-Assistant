"""Central configuration: environment loading, parsing, and validation.

All runtime knobs live here so the rest of the app never touches ``os.environ``
directly. ``load_settings()`` is cheap and pure; it does *not* require a Groq key
(so tests can run with a fake LLM). The key is only enforced when a real
:class:`~dualcore.llm.GroqLLM` is constructed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

VALID_DRIVERS = {"docker", "subprocess"}
VALID_PROFILES = {"basic", "ml"}

# Curated chat models offered in the UI selector: (model_id, friendly_label).
AVAILABLE_MODELS: list[tuple[str, str]] = [
    ("openai/gpt-oss-120b", "gpt-oss-120b · smartest"),
    ("llama-3.3-70b-versatile", "Llama 3.3 70B · balanced"),
    ("llama-3.1-8b-instant", "Llama 3.1 8B · fastest"),
    ("qwen/qwen3-32b", "Qwen3 32B"),
    ("openai/gpt-oss-20b", "gpt-oss-20b"),
    ("meta-llama/llama-4-scout-17b-16e-instruct", "Llama 4 Scout"),
]
VALID_MODELS = {mid for mid, _ in AVAILABLE_MODELS}

# Per-model output-token caps so one request fits Groq's free-tier tokens-per-minute
# limit (smaller models have a ~6k TPM ceiling). Large fallback = no cap for custom models.
MODEL_MAX_TOKENS = {
    "openai/gpt-oss-120b": 8000,
    "llama-3.3-70b-versatile": 8000,
    "llama-3.1-8b-instant": 3500,
    "qwen/qwen3-32b": 3500,
    "openai/gpt-oss-20b": 5500,
    "meta-llama/llama-4-scout-17b-16e-instruct": 8000,
}


def model_token_cap(model_id: str) -> int:
    """Max output tokens that fits the model's free-tier rate limit."""
    return MODEL_MAX_TOKENS.get(model_id, 32000)


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    """Immutable, validated application settings."""

    groq_api_key: str
    model: str = "openai/gpt-oss-120b"  # strongest coding model on Groq free tier
    max_tokens: int = 8192  # headroom for reasoning models (e.g. gpt-oss) so code isn't truncated
    temperature: float = 0.3

    # Sandbox
    sandbox_driver: str = "docker"  # "docker" | "subprocess"
    exec_timeout: int = 30          # wall-clock seconds per execution
    mem_limit_mb: int = 512
    cpu_limit: float = 1.0
    pids_limit: int = 256
    docker_image_basic: str = "dualcore-sandbox:basic"
    docker_image_ml: str = "dualcore-sandbox:ml"

    # Orchestration
    max_rounds: int = 6

    # Request limits (protect the Groq quota on a public deploy)
    max_requirement_chars: int = 8000
    max_instructions_chars: int = 4000

    # Flask
    debug: bool = False
    port: int = 5000

    def image_for(self, profile: str) -> str:
        """Return the sandbox Docker image name for a profile."""
        if profile == "ml":
            return self.docker_image_ml
        return self.docker_image_basic

    @property
    def has_llm(self) -> bool:
        return bool(self.groq_api_key)


def load_settings() -> Settings:
    """Build :class:`Settings` from the environment, validating as we go."""
    driver = os.environ.get("SANDBOX", "docker").strip().lower()
    if driver not in VALID_DRIVERS:
        raise ConfigError(
            f"SANDBOX must be one of {sorted(VALID_DRIVERS)}, got {driver!r}"
        )

    settings = Settings(
        groq_api_key=os.environ.get("GROQ_API_KEY", "").strip(),
        model=os.environ.get("MODEL", Settings.model).strip(),
        max_tokens=_get_int("MAX_TOKENS", Settings.max_tokens),
        temperature=_get_float("TEMPERATURE", Settings.temperature),
        sandbox_driver=driver,
        exec_timeout=_get_int("EXEC_TIMEOUT", Settings.exec_timeout),
        mem_limit_mb=_get_int("MEM_LIMIT_MB", Settings.mem_limit_mb),
        cpu_limit=_get_float("CPU_LIMIT", Settings.cpu_limit),
        pids_limit=_get_int("PIDS_LIMIT", Settings.pids_limit),
        max_rounds=_get_int("MAX_ROUNDS", Settings.max_rounds),
        debug=_get_bool("FLASK_DEBUG", Settings.debug),
        port=_get_int("PORT", Settings.port),
    )

    if settings.exec_timeout <= 0:
        raise ConfigError("EXEC_TIMEOUT must be positive")
    if settings.max_rounds <= 0:
        raise ConfigError("MAX_ROUNDS must be positive")
    return settings
