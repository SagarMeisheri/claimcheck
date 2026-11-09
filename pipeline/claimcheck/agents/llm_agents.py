"""LlmAgents: the extractor (reads the video, tags statements), the source summarizer (what the web sources found for
a claim say, in 1-2 sentences), and the speaker profiler (who a named speaker is, from search excerpts). None has
tools; searches run in code (tools/evidence.py). The source triage classifier is built here too."""

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
from ..schemas import ContradictionOut, CreatorProfileOut, ExtractionResult, PeopleOut, QaOut, ResearchPlan, SpeakerProfileOut, TldrOut, VideoPlan


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
        wrap_untrusted(f"{p.get('group', 'RELATED')} PAGE {p['n']}",
                       f"Title: {p['title']}\nSite: {p['site']}\nExcerpt: {screen_text(p['text'])[0]}")
        for p in callback_context.state["pages"])
    llm_request.contents.append(types.Content(role="user", parts=[types.Part(text=f"Pages:\n\n{blocks}\n\nSummarize what these excerpts say.")]))


# --- Q&A view --------------------------------------------------------------------------------------

def qa_agent(s: Settings, name: str = "qa_writer") -> LlmAgent:
    """Picks the questions for the Q&A view and the statements that answer them. The statements are read from state."""
    cfg = types.GenerateContentConfig()
    level = (s.summary_thinking or "default").strip().upper()
    if level != "DEFAULT":
        cfg.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel(level))
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.QA,
                    include_contents="none", output_schema=QaOut, output_key="qa", generate_content_config=cfg)


# --- Researching an answer -------------------------------------------------------------------------

def _research_cfg(s: Settings) -> types.GenerateContentConfig:
    cfg = types.GenerateContentConfig()
    level = (s.summary_thinking or "default").strip().upper()
    if level != "DEFAULT":
        cfg.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel(level))
    return cfg


def research_planner_agent(s: Settings, name: str = "research_planner") -> LlmAgent:
    """Turns an answer into checkable points, with new queries per point and the positions on a disputed issue."""
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.RESEARCH_PLAN, include_contents="none",
                    output_schema=ResearchPlan, output_key="plan", generate_content_config=_research_cfg(s))


def video_planner_agent(s: Settings, name: str = "video_planner") -> LlmAgent:
    """Plans the research of every answer of a video together: points per answer, and searches that serve several answers."""
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.RESEARCH_PLAN_VIDEO, include_contents="none",
                    output_schema=VideoPlan, output_key="plan", generate_content_config=_research_cfg(s))


def contradiction_agent(s: Settings, name: str = "contradiction") -> LlmAgent:
    """Says what was said and how the page differs, for an answer tagged contradicted (agents/contradiction.py)."""
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.CONTRADICTION, include_contents="none",
                    output_schema=ContradictionOut, output_key="contradiction", generate_content_config=_research_cfg(s))


def tldr_agent(s: Settings, name: str = "tldr") -> LlmAgent:
    """Writes the podcast profile's TL;DRs from a digest of the video's tags (agents/tldr.py)."""
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.TLDR, include_contents="none",
                    output_schema=TldrOut, output_key="tldr", generate_content_config=_research_cfg(s))


# --- Creator and speaker profiles ------------------------------------------------------------------

def _profile_cfg(s: Settings) -> types.GenerateContentConfig:
    """The profile writers think more than the other steps: they bring 20+ pages into one cited profile."""
    cfg = types.GenerateContentConfig()
    cfg.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel((s.profile_thinking or "medium").upper()))
    return cfg


def people_finder_agent(s: Settings, name: str = "people_finder") -> LlmAgent:
    """Who appears in a video, from its title, description and one search (agents/people.py)."""
    cfg = types.GenerateContentConfig()
    cfg.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel("LOW"))
    return LlmAgent(name=name, model=_model(s.profile_model, s), instruction=prompts.PEOPLE, include_contents="none",
                    output_schema=PeopleOut, output_key="people", generate_content_config=cfg)


def creator_profiler_agent(s: Settings, name: str = "creator_profiler") -> LlmAgent:
    cfg = _profile_cfg(s)
    return LlmAgent(name=name, model=_model(s.profile_model, s), instruction=prompts.PROFILE_CREATOR,
                    include_contents="none", output_schema=CreatorProfileOut, output_key="profile",
                    generate_content_config=cfg, before_model_callback=inject_pages)


def speaker_profiler_agent(s: Settings, name: str = "speaker_profiler") -> LlmAgent:
    cfg = _profile_cfg(s)
    return LlmAgent(name=name, model=_model(s.profile_model, s), instruction=prompts.PROFILE_SPEAKER,
                    include_contents="none", output_schema=SpeakerProfileOut, output_key="profile",
                    generate_content_config=cfg, before_model_callback=inject_pages)


# --- Source triage -----------------------------------------------------------------------------------

def tag_classifier(s: Settings, level: str = "MEDIUM") -> Any:
    """The classifier behind one answer tag: ADK's LlmClassifier on a Gemini model that counts its own tokens, at the thinking level the
    tag needs (the simple binaries run LOW, the ones that weigh evidence MEDIUM). A seam for tests."""
    from google.adk.labs.classifiers import LlmClassifier

    from ..guardrails.budget import metered_gemini

    return LlmClassifier(model=metered_gemini(s.tag_model),
                         generate_content_config=types.GenerateContentConfig(
                             thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel(level))))
