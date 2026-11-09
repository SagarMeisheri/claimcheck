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
    "flash-lite": (0.30, 2.50),        # gemini-3.5-flash-lite (cheaper option for the sources summary)
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
    summary_model: str = field(default_factory=lambda: _env("CLAIMCHECK_SUMMARY_MODEL", "gemini-3.8-flash"))
    # Thinking for the sources summary + match: minimal, low, medium, high or "default". Low keeps it ~$0.003 a claim.
    summary_thinking: str = field(default_factory=lambda: _env("CLAIMCHECK_SUMMARY_THINKING", "low"))
    # "Check sources for all statements" (agents/sources.py): the same search for every statement, a few at a time.
    # Source lookups (searches) per video in total: the button, "Check all" and the automatic ones together; earliest claims first, claims
    # with the same wording share one. 0 = no limit. The per-video cost cap applies as well.
    max_searches_per_video: int = int(_env("CLAIMCHECK_MAX_SEARCHES_PER_VIDEO", "200"))
    sources_concurrency: int = int(_env("CLAIMCHECK_SOURCES_CONCURRENCY", "5"))
    # Automatic source checking, so nobody has to press "Check sources" (agents/sources.py):
    #   auto_sources           after the whole video is read, look up every answer the planner finds something checkable in
    #   auto_sources_as_found  also start each answer's lookup as soon as it is saved, while the extractor is still
    #                          writing (implies the one above, which then picks up whatever was left)
    # A lookup started during extraction is paid from the same video budget as the extraction, whose cost is only
    # counted when it ends, so they are limited to auto_sources_stream_budget_usd / lookup_cost_estimate_usd.
    auto_sources: bool = _env("CLAIMCHECK_AUTO_SOURCES", "0") == "1"
    auto_sources_as_found: bool = _env("CLAIMCHECK_AUTO_SOURCES_AS_FOUND", "0") == "1"
    auto_sources_stream_budget_usd: float = float(_env("CLAIMCHECK_AUTO_SOURCES_STREAM_BUDGET_USD", "0.5"))
    tool_timeout_s: float = float(_env("CLAIMCHECK_TOOL_TIMEOUT_S", "60"))
    # Before a lookup, a classifier (ADK ClassifierNode, agents/sources.py) decides how to look the statement up:
    # skip (background, self-description, vague), related (one search), data or contested (one more search for
    # different figures or other perspectives, aimed with the speaker's and creator's profiles).
    # Researching an answer (agents/research.py): a planner turns the answer into checkable points with new queries (not the
    # answer's own words), one web request carrying at most research_max_searches queries finds the pages (10 in all), and every page it returns is kept. Only the search excerpts are
    # used: no page is fetched. If it fails, the lookup falls back to the plain search and summary.
    research_max_points: int = int(_env("CLAIMCHECK_RESEARCH_MAX_POINTS", "2"))
    research_max_searches: int = int(_env("CLAIMCHECK_RESEARCH_MAX_SEARCHES", "3"))  # queries per answer, sent in one web request
    # Rough costs, used only to plan budgets (the model calls are counted from tokens).
    research_plan_cost_estimate_usd: float = float(_env("CLAIMCHECK_RESEARCH_PLAN_COST_ESTIMATE_USD", "0.006"))  # the planner call
    # Answer tags (agents/qa_tags.py): one ADK classifier call per answer (answer type, claim type and the conditional conflict checks),
    # a second when it is researched (grounding, match, missing context); question types and the dynamic are batched once per video
    # (agents/interview.py).
    tag_answers: bool = _env("CLAIMCHECK_TAG_ANSWERS", "1") == "1"
    tag_model: str = field(default_factory=lambda: _env("CLAIMCHECK_TAG_MODEL", "gemini-3.8-flash"))
    tag_cost_estimate_usd: float = float(_env("CLAIMCHECK_TAG_COST_ESTIMATE_USD", "0.03"))  # one answer's two calls, the grounding one with ~30 pages
    # The podcast profile's TL;DRs (agents/tldr.py): one model call per video, again whenever its answers are checked.
    tldr: bool = _env("CLAIMCHECK_TLDR", "1") == "1"
    tldr_cost_estimate_usd: float = float(_env("CLAIMCHECK_TLDR_COST_ESTIMATE_USD", "0.02"))
    # Speaker profiles (agents/speakers.py): one web search + one model call per new named speaker, then reused.
    # A channel that isn't on the curated creator list is looked up on the web once (agents/creators.py) and remembered.
    profile_creators: bool = _env("CLAIMCHECK_PROFILE_CREATORS", "1") == "1"
    profile_speakers: bool = _env("CLAIMCHECK_PROFILE_SPEAKERS", "1") == "1"
    max_speaker_profiles: int = int(_env("CLAIMCHECK_MAX_SPEAKER_PROFILES", "6"))  # new profiles per video
    profile_model: str = field(default_factory=lambda: _env("CLAIMCHECK_PROFILE_MODEL", "gemini-3.8-flash"))
    profile_thinking: str = field(default_factory=lambda: _env("CLAIMCHECK_PROFILE_THINKING", "medium"))
    default_search_location: str = field(default_factory=lambda: _env("CLAIMCHECK_SEARCH_LOCATION", "in"))
    # YouTube API data older than this is refreshed (YouTube allows at most 30 days).
    youtube_refresh_days: int = int(_env("CLAIMCHECK_YOUTUBE_REFRESH_DAYS", "25"))

    prices: dict = field(default_factory=_prices)
    search_cost_usd: float = float(_env("CLAIMCHECK_SEARCH_COST_USD", "0.005"))
    # Rough cost of one sources summary, used only to plan how many lookups a video's budget can pay for
    # (the real cost is counted from tokens). ~$0.003 on Gemini 3.8 Flash with low thinking.


    @property
    def auto_sources_enabled(self) -> bool:
        """Whether lookups start by themselves, whenever that happens."""
        return self.auto_sources or self.auto_sources_as_found

    @property
    def max_streamed_lookups(self) -> int:
        """How many lookups may start while the extractor is still writing."""
        each = self.lookup_cost_estimate_usd
        return max(0, int(self.auto_sources_stream_budget_usd / each + 1e-9)) if each > 0 else 0

    @property
    def lookup_cost_estimate_usd(self) -> float:
        """The most one lookup can cost (the planner, its searches, the answer tags), for planning how many fit in a video's budget."""
        return self.search_cost_usd + self.research_plan_cost_estimate_usd + (self.tag_cost_estimate_usd if self.tag_answers else 0.0)


def get_settings() -> Settings:
    return Settings()
