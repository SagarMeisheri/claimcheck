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
    summarize_sources: bool = _env("CLAIMCHECK_SUMMARIZE_SOURCES", "1") == "1"
    summary_model: str = field(default_factory=lambda: _env("CLAIMCHECK_SUMMARY_MODEL", "gemini-3.8-flash"))
    # Thinking for the sources summary + match: minimal, low, medium, high or "default". Low keeps it ~$0.003 a claim.
    summary_thinking: str = field(default_factory=lambda: _env("CLAIMCHECK_SUMMARY_THINKING", "low"))
    # "Check sources for all statements" (agents/sources.py): the same search for every statement, a few at a time.
    # Searches per press (earliest claims first; press again for the rest). Claims with the same wording share one.
    sources_all_max_searches: int = int(_env("CLAIMCHECK_SOURCES_ALL_MAX_SEARCHES", "75"))
    sources_concurrency: int = int(_env("CLAIMCHECK_SOURCES_CONCURRENCY", "5"))
    # Automatic source checking, so nobody has to press "Check sources" (agents/sources.py):
    #   auto_sources           after the whole video is read, look up every answer the triage classifier doesn't skip
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
    # answer's own words), pages from the speaker's own organisation and the episode itself are set aside, the best pages are
    # read (not only their search excerpts) and each finding carries a quote checked against the page. If it fails, the
    # lookup falls back to the plain search and summary.
    research_sources: bool = _env("CLAIMCHECK_RESEARCH_SOURCES", "1") == "1"
    research_max_points: int = int(_env("CLAIMCHECK_RESEARCH_MAX_POINTS", "2"))
    research_pages: int = int(_env("CLAIMCHECK_RESEARCH_PAGES", "5"))  # pages read per answer
    research_retry: bool = _env("CLAIMCHECK_RESEARCH_RETRY", "1") == "1"  # one rewritten-query retry for an unanswered point
    # Rough costs, used only to plan budgets (the model calls are counted from tokens; extract_cost_usd is an assumption).
    extract_cost_usd: float = float(_env("CLAIMCHECK_EXTRACT_COST_USD", "0.005"))
    research_cost_estimate_usd: float = float(_env("CLAIMCHECK_RESEARCH_COST_ESTIMATE_USD", "0.012"))  # planner + reader
    # Opinion assessment (agents/opinion.py): for opinions and contested answers, what the governing side and the opposition say,
    # evidenced bias signals from the speaker's and show's profiles, and a judge's short assessment. Needs research_sources.
    opinion_check: bool = _env("CLAIMCHECK_OPINION_CHECK", "1") == "1"
    opinion_cost_estimate_usd: float = float(_env("CLAIMCHECK_OPINION_COST_ESTIMATE_USD", "0.03"))  # stance plan+search+read, bias, judge
    triage_sources: bool = _env("CLAIMCHECK_TRIAGE_SOURCES", "1") == "1"
    counter_search: bool = _env("CLAIMCHECK_COUNTER_SEARCH", "1") == "1"
    triage_model: str = field(default_factory=lambda: _env("CLAIMCHECK_TRIAGE_MODEL", "gemini-3.8-flash"))
    # Speaker profiles (agents/speakers.py): one web search + one model call per new named speaker, then reused.
    # A channel that isn't on the curated creator list is looked up on the web once (agents/creators.py) and remembered.
    profile_creators: bool = _env("CLAIMCHECK_PROFILE_CREATORS", "1") == "1"
    profile_speakers: bool = _env("CLAIMCHECK_PROFILE_SPEAKERS", "1") == "1"
    max_speaker_profiles: int = int(_env("CLAIMCHECK_MAX_SPEAKER_PROFILES", "6"))  # new profiles per video
    profile_model: str = field(default_factory=lambda: _env("CLAIMCHECK_PROFILE_MODEL", "gemini-3.8-flash"))
    default_search_location: str = field(default_factory=lambda: _env("CLAIMCHECK_SEARCH_LOCATION", "in"))
    # YouTube API data older than this is refreshed (YouTube allows at most 30 days).
    youtube_refresh_days: int = int(_env("CLAIMCHECK_YOUTUBE_REFRESH_DAYS", "25"))

    prices: dict = field(default_factory=_prices)
    search_cost_usd: float = float(_env("CLAIMCHECK_SEARCH_COST_USD", "0.005"))
    # Rough cost of one sources summary, used only to plan how many lookups a video's budget can pay for
    # (the real cost is counted from tokens). ~$0.003 on Gemini 3.8 Flash with low thinking.
    summary_cost_estimate_usd: float = float(_env("CLAIMCHECK_SUMMARY_COST_ESTIMATE_USD", "0.003"))

    # Rough cost of one triage call (~$0.0015 measured on Flash with low thinking). The real cost is counted from tokens.
    triage_cost_estimate_usd: float = float(_env("CLAIMCHECK_TRIAGE_COST_ESTIMATE_USD", "0.0015"))

    @property
    def counter_enabled(self) -> bool:
        """The second search needs the classifier: without it there is no way to pick the statements that get one."""
        return self.triage_sources and self.counter_search

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
        """The most one lookup can cost (triage, both searches, the summary), for planning a "Check sources for all
        statements" press. Statements the classifier routes to one search or skips cost less."""
        if self.research_sources:  # points x searches, pages read, planner and reader
            searches = max(1, self.research_max_points) + 1
            return (self.search_cost_usd * searches + self.extract_cost_usd * (2 if self.research_retry else 1)
                    + self.research_cost_estimate_usd * (2 if self.research_retry else 1)
                    + (self.opinion_cost_estimate_usd if self.opinion_check else 0.0)
                    + (self.triage_cost_estimate_usd if self.triage_sources else 0.0))
        searches = 2 if self.counter_enabled else 1
        return (self.search_cost_usd * searches + (self.summary_cost_estimate_usd if self.summarize_sources else 0.0)
                + (self.triage_cost_estimate_usd if self.triage_sources else 0.0))


def get_settings() -> Settings:
    return Settings()
