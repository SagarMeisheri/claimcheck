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
from ..schemas import (Assessment, BiasRead, CreatorProfileOut, ExtractionResult, PageReading, QaOut, QueryRewrite, ResearchPlan,
                       SourcesSummary, SpeakerProfileOut, StancePlan, StanceReading)


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


def summarizer_agent(s: Settings, name: str = "source_summarizer") -> LlmAgent:
    # Gemini 3 models are meant to run at their default temperature (lower can loop), so none is set here.
    cfg = types.GenerateContentConfig()
    level = (s.summary_thinking or "default").strip().upper()
    if level != "DEFAULT":
        cfg.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel(level))
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.SUMMARIZE,
                    include_contents="none", output_schema=SourcesSummary, output_key="summary",
                    generate_content_config=cfg, before_model_callback=inject_pages)


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


def inject_research_pages(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """before_model_callback on the page reader: the pages, numbered, as untrusted data (instruction-like lines removed)."""
    blocks = "\n\n".join(
        wrap_untrusted(f"PAGE {p['n']}",
                       f"Title: {p['title']}\nSite: {p['site']}\nFrom: {p['origin']}\nDate: {p.get('date') or 'unknown'}\n"
                       f"Text: {screen_text(p['text'])[0]}")
        for p in callback_context.state["pages"])
    llm_request.contents.append(types.Content(role="user", parts=[types.Part(text=f"Pages:\n\n{blocks}\n\nWrite the findings.")]))


def page_reader_agent(s: Settings, name: str = "page_reader") -> LlmAgent:
    """Reads the pages for the points and writes findings, each with a quote that code then checks against the page."""
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.READ_PAGES, include_contents="none",
                    output_schema=PageReading, output_key="reading", generate_content_config=_research_cfg(s),
                    before_model_callback=inject_research_pages)


def query_rewriter_agent(s: Settings, name: str = "query_rewriter") -> LlmAgent:
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.REWRITE_QUERIES, include_contents="none",
                    output_schema=QueryRewrite, output_key="rewrite", generate_content_config=_research_cfg(s))


# --- Opinion assessment (agents/opinion.py) --------------------------------------------------------

def stance_planner_agent(s: Settings, name: str = "stance_planner") -> LlmAgent:
    """Names the issue an answer takes a side on and writes the same kind of queries for the governing side and the opposition."""
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.STANCE_PLAN, include_contents="none",
                    output_schema=StancePlan, output_key="stance_plan", generate_content_config=_research_cfg(s))


def stance_reader_agent(s: Settings, name: str = "stance_reader") -> LlmAgent:
    """Reads pages for what each camp says on the issue; every quote is then checked against the page."""
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.READ_STANCES, include_contents="none",
                    output_schema=StanceReading, output_key="stance_reading", generate_content_config=_research_cfg(s),
                    before_model_callback=inject_research_pages)


def bias_agent(s: Settings, name: str = "bias_agent") -> LlmAgent:
    """Reads the answer against the speaker and show profiles and writes quoted signals (checked in code), never a verdict."""
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.BIAS_READ, include_contents="none",
                    output_schema=BiasRead, output_key="bias_read", generate_content_config=_research_cfg(s))


def judge_agent(s: Settings, name: str = "opinion_judge") -> LlmAgent:
    """Merges the source findings, the two camps' stances and the checked signals into the assessment a reader sees."""
    return LlmAgent(name=name, model=_model(s.summary_model, s), instruction=prompts.JUDGE, include_contents="none",
                    output_schema=Assessment, output_key="assessment", generate_content_config=_research_cfg(s))


# --- Creator and speaker profiles ------------------------------------------------------------------

def creator_profiler_agent(s: Settings, name: str = "creator_profiler") -> LlmAgent:
    cfg = types.GenerateContentConfig()
    cfg.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel("LOW"))
    return LlmAgent(name=name, model=_model(s.profile_model, s), instruction=prompts.PROFILE_CREATOR,
                    include_contents="none", output_schema=CreatorProfileOut, output_key="profile",
                    generate_content_config=cfg, before_model_callback=inject_pages)


def speaker_profiler_agent(s: Settings, name: str = "speaker_profiler") -> LlmAgent:
    cfg = types.GenerateContentConfig()
    cfg.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel("LOW"))
    return LlmAgent(name=name, model=_model(s.profile_model, s), instruction=prompts.PROFILE_SPEAKER,
                    include_contents="none", output_schema=SpeakerProfileOut, output_key="profile",
                    generate_content_config=cfg, before_model_callback=inject_pages)


# --- Source triage -----------------------------------------------------------------------------------

def triage_classifier(s: Settings) -> Any:
    """The classifier behind the triage ClassifierNode: ADK's LlmClassifier on a Gemini model that counts its own
    tokens (the classifier calls the model directly, outside the budget plugin). A seam for tests."""
    from google.adk.labs.classifiers import LlmClassifier

    from ..guardrails.budget import metered_gemini

    return LlmClassifier(model=metered_gemini(s.triage_model),
                         generate_content_config=types.GenerateContentConfig(
                             thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel("LOW"))))
