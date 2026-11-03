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
from ..schemas import BatchJudgeOutput, BatchTriage, ExtractionResult, JudgeOutput, KnowledgeResult, SearchPlan, TriageResult


def _model(name: str, settings: Settings) -> Any:
    return name


def _cfg(temperature: float = 0.2) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(temperature=temperature)


# --- Callbacks ------------------------------------------------------------------------

# Empty-but-valid outputs, so a skipped stage still satisfies its output schema.
_EMPTY = {
    "triage": {"worthiness": 0, "factual_density": "low", "speaker_type": "other", "pestle_mix": {},
               "never_share": 0, "reason": "skipped"},
    "extractor": {"claims": [], "summary": ""},
}


def _skip(agent_name: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=json.dumps(_EMPTY.get(agent_name, {})))])


def skip_if_gated(callback_context: CallbackContext) -> Optional[types.Content]:
    """before_agent_callback: once a gate has decided to skip the episode, later LLM stages do nothing."""
    if callback_context.state.get("gate", {}).get("skip"):
        return _skip(callback_context.agent_name)
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
    llm_request.contents.append(types.Content(role="user", parts=[part, types.Part(text="Extract the claims from this video.")]))


def inject_sources(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """before_model_callback on the judge: adds fetched sources as delimited, untrusted data.

    The judge sees exactly the text the quote check will later search, so a quote
    that passes the check really is in what the judge read.
    """
    ctx = get_context()
    docs = ctx.evidence.get(callback_context.state["claim_key"], {})
    items = list(docs.items())
    if callback_context.state.get("reorder_sources"):
        items.reverse()
    if not items:
        blocks = "No sources were found."
    else:
        blocks = "\n\n".join(
            wrap_untrusted(f"SOURCE {i + 1}", f"URL: {url}\nTitle: {d.get('title', '')}\nPublished: {d.get('publish_date') or 'unknown'}\n\n{d['text']}")
            for i, (url, d) in enumerate(items)
        )
    llm_request.contents.append(types.Content(role="user", parts=[types.Part(text=f"Sources:\n\n{blocks}\n\nReturn your verdict.")]))


# --- Agents -------------------------------------------------------------------------

def triage_agent(s: Settings) -> LlmAgent:
    return LlmAgent(name="triage", model=_model(s.fast_model, s), instruction=prompts.TRIAGE,
                    include_contents="none", output_schema=TriageResult, output_key="triage",
                    generate_content_config=_cfg(0.0), before_agent_callback=skip_if_gated)


def extractor_agent(s: Settings) -> LlmAgent:
    cfg = _cfg(0.1)
    level = (s.extract_thinking or "default").strip().upper()
    if level != "DEFAULT":
        cfg.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel(level))
    return LlmAgent(name="extractor", model=_model(s.fast_model, s), instruction=prompts.EXTRACT,
                    include_contents="none", output_schema=ExtractionResult, output_key="extraction",
                    generate_content_config=cfg, before_agent_callback=skip_if_gated,
                    before_model_callback=inject_video)


def planner_agent(s: Settings) -> LlmAgent:
    return LlmAgent(name="planner", model=_model(s.fast_model, s), instruction=prompts.PLAN,
                    include_contents="none", output_schema=SearchPlan, output_key="plan",
                    generate_content_config=_cfg(0.0))


def judge_agent(s: Settings, name: str = "judge") -> LlmAgent:
    return LlmAgent(name=name, model=_model(s.judge_model, s), instruction=prompts.JUDGE,
                    include_contents="none", output_schema=JudgeOutput, output_key=name,
                    generate_content_config=_cfg(0.0), before_model_callback=inject_sources)


# --- Automatic whole-video verification (agents/video_verifier.py). Cheap model; claims arrive through state. ---

def inject_group_sources(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """before_model_callback on the batch judge: the fetched sources for this group, as untrusted blocks."""
    ctx = get_context()
    docs = ctx.evidence.get(callback_context.state["claim_key"], {})
    if not docs:
        blocks = "No sources were found."
    else:
        blocks = "\n\n".join(
            wrap_untrusted(f"SOURCE {i + 1}", f"URL: {url}\nTitle: {d.get('title', '')}\nPublished: {d.get('publish_date') or 'unknown'}\n\n{d['text']}")
            for i, (url, d) in enumerate(docs.items()))
    llm_request.contents.append(types.Content(role="user", parts=[types.Part(text=f"Sources:\n\n{blocks}\n\nReturn a verdict for every claim.")]))


def batch_triage_agent(s: Settings) -> LlmAgent:
    return LlmAgent(name="batch_triage", model=_model(s.lite_model, s), instruction=prompts.TRIAGE_BATCH,
                    include_contents="none", output_schema=BatchTriage, output_key="batch_triage",
                    generate_content_config=_cfg(0.0))


def knowledge_agent(s: Settings) -> LlmAgent:
    return LlmAgent(name="knowledge", model=_model(s.lite_model, s), instruction=prompts.KNOWLEDGE,
                    include_contents="none", output_schema=KnowledgeResult, output_key="knowledge",
                    generate_content_config=_cfg(0.0))


def batch_judge_agent(s: Settings, name: str = "batch_judge") -> LlmAgent:
    return LlmAgent(name=name, model=_model(s.auto_judge_model, s), instruction=prompts.JUDGE_BATCH,
                    include_contents="none", output_schema=BatchJudgeOutput, output_key="batch_judge",
                    generate_content_config=_cfg(0.0), before_model_callback=inject_group_sources)
