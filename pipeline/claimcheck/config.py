"""Runtime configuration from environment variables. Models and limits live here so they can be changed
without a deploy."""

from __future__ import annotations

import json
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


# USD per 1M tokens (input, output), matched by substring of the model id; the first match wins.
# Source: https://aistudio.google.com/docs/pricing (checked 3 Nov 2026). Gemini 3.8 Flash is $0.75/$3.75 until
# 31 Dec 2026 and $1.50/$7.50 from 1 Jan 2027: the later price is used so the cost cap never undercounts.
# Override with CLAIMCHECK_PRICES_JSON='{"gemini-3.8-flash": [0.75, 3.75]}'.
_DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "flash-lite": (0.30, 2.50),        # gemini-3.5-flash-lite (sources summary)
    "gemini-3.8-flash": (1.50, 7.50),
}


def _prices() -> dict[str, tuple[float, float]]:
    prices = dict(_DEFAULT_PRICES)
    raw = _env("CLAIMCHECK_PRICES_JSON")
    if raw:
        prices.update({k: (float(v[0]), float(v[1])) for k, v in json.loads(raw).items()})
    return prices


@dataclass(frozen=True)
class Settings:
    # Models
    fast_model: str = field(default_factory=lambda: _env("CLAIMCHECK_FAST_MODEL", "gemini-3.8-flash"))
    # "agentic" (default): model reads the transcript first and loads frames on demand. "static": fixed low-fps fallback.
    video_processing: str = field(default_factory=lambda: _env("CLAIMCHECK_VIDEO_PROCESSING", "agentic"))
    # How long the extractor thinks before it starts writing statements: minimal, low, medium, high, or "default".
    extract_thinking: str = field(default_factory=lambda: _env("CLAIMCHECK_EXTRACT_THINKING", "low"))
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

    # Limits
    # Covers the first pass plus every source search for the same video.
    max_cost_usd_per_episode: float = float(_env("CLAIMCHECK_MAX_COST_USD", "3.0"))
    # Sources: one Parallel search per claim, whatever it returns is shown (tools/evidence.py).
    sources_per_claim: int = int(_env("CLAIMCHECK_SOURCES_PER_CLAIM", "5"))
    sources_search_mode: str = field(default_factory=lambda: _env("CLAIMCHECK_SOURCES_SEARCH_MODE", "fast"))  # turbo | fast | basic | advanced
    excerpt_chars: int = int(_env("CLAIMCHECK_EXCERPT_CHARS", "320"))
    # One short neutral line per source, written by a cheap model from the page text (agents/sources.py). If it
    # fails or the budget runs out, the sources are still saved and the excerpt is shown instead.
    summarize_sources: bool = _env("CLAIMCHECK_SUMMARIZE_SOURCES", "1") == "1"
    summary_model: str = field(default_factory=lambda: _env("CLAIMCHECK_SUMMARY_MODEL", "gemini-3.5-flash-lite"))
    # "Check sources for all claims" (agents/sources.py): the same search for every claim, a few at a time.
    # Searches per press (earliest claims first; press again for the rest). Claims with the same wording share one.
    sources_all_max_searches: int = int(_env("CLAIMCHECK_SOURCES_ALL_MAX_SEARCHES", "25"))
    sources_concurrency: int = int(_env("CLAIMCHECK_SOURCES_CONCURRENCY", "5"))
    auto_sources: bool = _env("CLAIMCHECK_AUTO_SOURCES", "0") == "1"  # run it right after extraction
    tool_timeout_s: float = float(_env("CLAIMCHECK_TOOL_TIMEOUT_S", "60"))
    # YouTube API data older than this is refreshed (YouTube allows at most 30 days).
    youtube_refresh_days: int = int(_env("CLAIMCHECK_YOUTUBE_REFRESH_DAYS", "25"))

    prices: dict = field(default_factory=_prices)
    search_cost_usd: float = float(_env("CLAIMCHECK_SEARCH_COST_USD", "0.005"))


def get_settings() -> Settings:
    return Settings()
