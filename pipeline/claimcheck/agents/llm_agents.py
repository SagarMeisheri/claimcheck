"""LlmAgent definitions. Each has an output schema and no tools: web searches run in code (tools/evidence.py)."""

from __future__ import annotations

import json
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from .. import prompts
from ..config import Settings
from ..context import get_context
from ..guardrails.injection import wrap_untrusted
from ..schemas import BatchPick, BatchTriage, ExtractionResult, SearchPlan, SourcePick


def _model(name: str, settings: Settings) -> Any:
    """The model for an agent. A seam for tests, which swap in a scripted model."""
    return name


def _cfg(temperature: float = 0.2) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(temperature=temperature)


# --- Callbacks ------------------------------------------------------------------------

def skip_if_gated(callback_context: CallbackContext) -> Optional[types.Content]:
    """before_agent_callback: once a gate has decided to skip the video, the extractor does nothing."""
    if callback_context.state.get("gate", {}).get("skip"):
        return types.Content(role="model", parts=[types.Part(text=json.dumps({"claims": [], "summary": ""}))])
    return None


def inject_video(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """before_model_callback on the extractor: adds the YouTube URL as a video part.

    Agentic processing reads the transcript first and loads only the frames it needs.
    Static mode is the fallback: low fps and low media resolution.
    """
    ctx = get_context()
    url = callback_context.state["video_url"]
    part = types.Part(file_data=types.FileData(file_uri=url, mime_type="video/mp4"))
    if ctx.settings.video_processing == "agentic":
        part.media_processing = types.MediaProcessing.AGENTIC
    else:
        part.media_processing = types.MediaProcessing.STATIC
        part.video_metadata = types.VideoMetadata(fps=ctx.settings.static_fps)
        part.media_resolution = types.PartMediaResolution(level=types.PartMediaResolutionLevel.MEDIA_RESOLUTION_LOW)
    llm_request.contents.append(types.Content(role="user", parts=[part, types.Part(text="Tag the statements in this video.")]))


def _source_blocks(key: str) -> str:
    """The fetched pages for one search key, as delimited, untrusted blocks.

    The picker sees exactly the text the quote check will later search, so a quote that passes the check really
    is on the page the picker read.
    """
    docs = get_context().evidence.get(key, {})
    if not docs:
        return "No sources were found."
    return "\n\n".join(
        wrap_untrusted(f"SOURCE {i + 1}", f"URL: {url}\nTitle: {d.get('title', '')}\nPublished: {d.get('publish_date') or 'unknown'}\n\n{d['text']}")
        for i, (url, d) in enumerate(docs.items()))


def inject_sources(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """before_model_callback on both pickers: adds the fetched pages as untrusted data."""
    blocks = _source_blocks(callback_context.state["claim_key"])
    llm_request.contents.append(types.Content(role="user", parts=[types.Part(text=f"Sources:\n\n{blocks}\n\nReturn the sentences.")]))


# --- First pass -----------------------------------------------------------------------

def extractor_agent(s: Settings) -> LlmAgent:
    cfg = _cfg(0.1)
    level = (s.extract_thinking or "default").strip().upper()
    if level != "DEFAULT":
        cfg.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel(level))
    return LlmAgent(name="extractor", model=_model(s.fast_model, s), instruction=prompts.EXTRACT,
                    include_contents="none", output_schema=ExtractionResult, output_key="extraction",
                    generate_content_config=cfg, before_agent_callback=skip_if_gated,
                    before_model_callback=inject_video)


# --- Sources for one claim ------------------------------------------------------------

def planner_agent(s: Settings) -> LlmAgent:
    return LlmAgent(name="planner", model=_model(s.fast_model, s), instruction=prompts.PLAN,
                    include_contents="none", output_schema=SearchPlan, output_key="plan",
                    generate_content_config=_cfg(0.0))


def picker_agent(s: Settings) -> LlmAgent:
    return LlmAgent(name="picker", model=_model(s.fast_model, s), instruction=prompts.PICK,
                    include_contents="none", output_schema=SourcePick, output_key="picked",
                    generate_content_config=_cfg(0.0), before_model_callback=inject_sources)


# --- Sources for a whole video (cheap model; claims arrive through state) ----------------

def batch_triage_agent(s: Settings) -> LlmAgent:
    return LlmAgent(name="batch_triage", model=_model(s.lite_model, s), instruction=prompts.TRIAGE_BATCH,
                    include_contents="none", output_schema=BatchTriage, output_key="batch_triage",
                    generate_content_config=_cfg(0.0))


def batch_picker_agent(s: Settings, name: str = "batch_picker") -> LlmAgent:
    return LlmAgent(name=name, model=_model(s.lite_model, s), instruction=prompts.PICK_BATCH,
                    include_contents="none", output_schema=BatchPick, output_key="batch_picked",
                    generate_content_config=_cfg(0.0), before_model_callback=inject_sources)
