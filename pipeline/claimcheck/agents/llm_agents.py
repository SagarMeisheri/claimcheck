"""LlmAgents: the extractor (reads the video, tags statements) and the source summarizer (what the web
sources found for a claim say, in 1-2 sentences). Neither has tools; searches run in code (tools/evidence.py)."""

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
from ..guardrails.injection import screen_text, wrap_untrusted
from ..schemas import ExtractionResult, SourcesSummary


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


# --- Source summaries ------------------------------------------------------------------------

def inject_pages(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """before_model_callback on the summarizer: the pages, numbered, as untrusted data (instruction-like lines removed)."""
    blocks = "\n\n".join(
        wrap_untrusted(f"PAGE {p['n']}", f"Title: {p['title']}\nSite: {p['site']}\nExcerpt: {screen_text(p['text'])[0]}")
        for p in callback_context.state["pages"])
    llm_request.contents.append(types.Content(role="user", parts=[types.Part(text=f"Pages:\n\n{blocks}\n\nSummarize what these excerpts say.")]))


def summarizer_agent(s: Settings, name: str = "source_summarizer") -> LlmAgent:
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.SUMMARIZE,
                    include_contents="none", output_schema=SourcesSummary, output_key="summary",
                    generate_content_config=_cfg(0.0), before_model_callback=inject_pages)
