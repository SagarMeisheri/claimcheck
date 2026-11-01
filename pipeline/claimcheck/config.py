"""Runtime configuration from environment variables. Models and modes live here so
they can be swapped without a deploy (e.g. if Gemini 4 Argon pricing is too high)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env before the Settings class body runs (some defaults are read at import time).
# Real environment variables win over the file. Checks pipeline/.env, then the repo root .env.
_PIPELINE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_PIPELINE_DIR / ".env", override=False)
load_dotenv(_PIPELINE_DIR.parent / ".env", override=False)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # Models
    fast_model: str = field(default_factory=lambda: _env("CLAIMCHECK_FAST_MODEL", "gemini-3.8-flash"))
    judge_model: str = field(default_factory=lambda: _env("CLAIMCHECK_JUDGE_MODEL", "gemini-4-argon"))
    embedding_model: str = field(default_factory=lambda: _env("CLAIMCHECK_EMBEDDING_MODEL", "gemini-embedding-001"))
    embedding_dims: int = int(_env("CLAIMCHECK_EMBEDDING_DIMS", "768"))
    # "agentic" (default): model reads the transcript first and loads frames on demand. "static": fixed low-fps fallback.
    video_processing: str = field(default_factory=lambda: _env("CLAIMCHECK_VIDEO_PROCESSING", "agentic"))
    static_fps: float = float(_env("CLAIMCHECK_STATIC_FPS", "0.2"))

    # Keys
    gemini_api_key: str = field(default_factory=lambda: _env("GOOGLE_API_KEY"))
    parallel_api_key: str = field(default_factory=lambda: _env("PARALLEL_API_KEY"))
    youtube_api_key: str = field(default_factory=lambda: _env("YOUTUBE_API_KEY"))
    supabase_url: str = field(default_factory=lambda: _env("SUPABASE_URL"))
    supabase_service_key: str = field(default_factory=lambda: _env("SUPABASE_SERVICE_ROLE_KEY"))
    pipeline_secret: str = field(default_factory=lambda: _env("PIPELINE_SHARED_SECRET"))

    # Model Armor (optional; leave empty to rely on the built-in heuristic screen only)
    model_armor_prompt_template: str = field(default_factory=lambda: _env("MODEL_ARMOR_PROMPT_TEMPLATE"))
    model_armor_tool_template: str = field(default_factory=lambda: _env("MODEL_ARMOR_TOOL_TEMPLATE"))

    # Limits and guardrails
    max_cost_usd_per_episode: float = float(_env("CLAIMCHECK_MAX_COST_USD", "3.0"))
    max_searches_per_claim: int = int(_env("CLAIMCHECK_MAX_SEARCHES_PER_CLAIM", "4"))
    tool_timeout_s: float = float(_env("CLAIMCHECK_TOOL_TIMEOUT_S", "60"))
    cache_similarity: float = float(_env("CLAIMCHECK_CACHE_SIMILARITY", "0.92"))
    cache_max_age_days: int = int(_env("CLAIMCHECK_CACHE_MAX_AGE_DAYS", "90"))
    # Dev flag: ignore the triage worthiness threshold (the never-check share gate still applies).
    skip_worthiness: bool = _env("CLAIMCHECK_SKIP_WORTHINESS", "0") == "1"
    enable_escalation: bool = _env("CLAIMCHECK_ENABLE_ESCALATION", "1") == "1"

    # USD per 1M tokens (input, output). Argon is an ASSUMPTION until Google publishes pricing.
    prices: dict = field(default_factory=lambda: {
        "gemini-3.8-flash": (0.75, 3.75),
        "gemini-4-argon": (2.50, 15.0),
    })
    search_cost_usd: float = 0.005
    extract_cost_usd: float = 0.001
    task_core_cost_usd: float = 0.025


def get_settings() -> Settings:
    return Settings()
