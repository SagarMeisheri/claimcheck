"""EpisodePipeline: the ADK app that turns one YouTube URL into a tagged breakdown of what was said.

Before the pipeline: the video's channel row and, if the channel is a known show, its `creators` profile.

EpisodePipeline (SequentialAgent)
  IngestGate       code   metadata + input guardrails (public, finished)
  ExtractorAgent   LLM    agentic video -> tagged statements (with what was being discussed), sections, summary
  ClaimFilter      code   cap, content policy in code, which statements can have sources looked up, sections cleaned
  SpeakerProfiler  code   a profile for every named speaker, from the creator profile, the `speakers` table or a
                          web search (agents/speakers.py)
  Publisher        code   saves statements, sections and the result (sources are looked up later: sources.py)

The viewer sees the steps as a checklist (EpisodeContext.steps, saved in episodes.progress).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from google.adk.agents import SequentialAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import InMemoryRunner
from google.genai import types

from ..config import Settings, get_settings
from ..context import Budget, EpisodeContext, is_budget_error, report_progress, set_context, set_step
from ..guardrails.budget import BudgetPlugin
from ..guardrails.input_checks import parse_video_id
from ..policy import load_policy
from ..store import make_store
from .llm_agents import extractor_agent
from .speakers import SpeakerProfiler
from .streaming import StatementStreamer
from .stages import ClaimFilter, IngestGate, Publisher

log = logging.getLogger("claimcheck")
APP = "claimcheck"


def build_stages(settings: Settings) -> list:
    """Fresh (unparented) stage agents, so they can be placed in the pipeline or in the adk web wrapper."""
    return [
        IngestGate(name="ingest_gate"),
        extractor_agent(settings),
        ClaimFilter(name="claim_filter"),
        SpeakerProfiler(name="speaker_profiler"),
        Publisher(name="publisher"),
    ]


def build_pipeline(settings: Settings) -> SequentialAgent:
    return SequentialAgent(name="episode_pipeline", sub_agents=build_stages(settings))


# (agent name, label shown while it runs, % complete once it has finished)
STAGE_PROGRESS = [
    ("ingest_gate", "Checking the video details", 12),
    ("extractor", "Reading the video, tagging statements and sections", 82),
    ("claim_filter", "Applying the content policy", 86),
    ("speaker_profiler", "Building speaker profiles", 96),
    ("publisher", "Saving results", 100),
]
_STAGE_INDEX = {name: i for i, (name, _, _) in enumerate(STAGE_PROGRESS)}

# The checklist the viewer sees: "creator" runs before the pipeline, the rest are its stages.
CREATOR_STEP = ("creator", "Matching the channel to a creator profile")


def initial_steps() -> list[dict[str, Any]]:
    return [{"key": CREATOR_STEP[0], "label": CREATOR_STEP[1], "status": "pending"}] + [
        {"key": name, "label": label, "status": "pending"} for name, label, _ in STAGE_PROGRESS]


def _step_detail(ev: Any) -> Optional[str]:
    """A stage's short result text ('12 of 40 statements ...'), shown under its step."""
    if getattr(ev, "author", "") not in ("claim_filter", "speaker_profiler"):
        return None
    parts = getattr(getattr(ev, "content", None), "parts", None) or []
    text = "".join(getattr(p, "text", "") or "" for p in parts).strip()
    return text[:160] if text and not text.startswith("{") else None


def make_plugins_factory(settings: Settings):
    def factory() -> list:
        plugins: list = [BudgetPlugin()]
        if settings.model_armor_prompt_template or settings.model_armor_tool_template:
            from google.adk.integrations.model_armor import ModelArmorConfig, ModelArmorPlugin

            plugins.append(ModelArmorPlugin(config=ModelArmorConfig(
                prompt_template_name=settings.model_armor_prompt_template or None,
                tool_output_template_name=settings.model_armor_tool_template or None,
                block_on_screening_failure=False,
            )))
        return plugins
    return factory


async def run_episode(url: str, *, settings: Optional[Settings] = None, store: Any = None,
                      episode_id: Optional[str] = None, submitted_by: Optional[str] = None) -> dict[str, Any]:
    settings = settings or get_settings()
    policy = load_policy()
    store = store or make_store(settings)
    video_id = parse_video_id(url)
    if not video_id:
        return {"status": "rejected", "reason": "Not a valid YouTube video URL."}

    from ..tools.youtube import fetch_metadata  # one YouTube API call, shared with the ingest gate
    meta = await fetch_metadata(video_id, settings)
    from ..channels import resolve_channel

    channel = await resolve_channel(store, meta)
    try:
        creator = await store.get_creator_by_channel(meta.get("channel_id") or "")
    except Exception:  # a profile only adds context; the video is analysed without it
        log.exception("creator lookup failed for %s", meta.get("channel_id"))
        creator = None
    episode_id = episode_id or await store.create_episode({
        "youtube_video_id": video_id, "channel_id": (channel or {}).get("id"), "title": meta.get("title"),
        "status": "queued", "submitted_by": submitted_by,
    })
    # Save what the metadata call returned right away, so the home page can show the title, thumbnail
    # and length while the video is still being analysed.
    await store.update_episode(episode_id, {k: v for k, v in {
        "status": "processing", "title": meta.get("title") or None, "duration_s": meta.get("duration_s") or None,
        "published_at": meta.get("published_at") or None, "channel_id": (channel or {}).get("id"),
        "creator_id": (creator or {}).get("id"),
    }.items() if v is not None})

    ec = EpisodeContext(episode_id=episode_id, video_id=video_id, settings=settings, policy=policy,
                        store=store, budget=Budget(cap_usd=settings.max_cost_usd_per_episode),
                        plugins_factory=make_plugins_factory(settings), duration_s=int(meta.get("duration_s") or 0),
                        creator=creator, steps=initial_steps())
    set_step(ec, CREATOR_STEP[0], "done" if creator else "skipped",
             creator["podcast"] if creator else "Not one of the shows with a creator profile")
    token = set_context(ec)
    runner = InMemoryRunner(agent=build_pipeline(settings), app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="pipeline", state={
        "video_url": f"https://www.youtube.com/watch?v={video_id}", "episode_id": episode_id,
    })
    try:
        set_step(ec, STAGE_PROGRESS[0][0], "running")
        await report_progress(ec, STAGE_PROGRESS[0][1], 2)
        await store.clear_statements_without_sources(episode_id)  # leftovers from an earlier attempt would clash with the new rows
        streamer = StatementStreamer(ec)
        last = -1
        # SSE streaming: the extractor's reply arrives in pieces and each finished statement is saved at once.
        async for ev in runner.run_async(user_id="pipeline", session_id=session.id, run_config=RunConfig(streaming_mode=StreamingMode.SSE),
                                         new_message=types.Content(role="user", parts=[types.Part(text="Check this episode.")])):
            if getattr(ev, "partial", False):  # a piece of a reply, not a finished stage
                await streamer.on_event(ev)
                continue
            i = _STAGE_INDEX.get(getattr(ev, "author", ""), -1)
            if i >= 0:
                log.info("stage %s finished at +%.1fs", ev.author, time.monotonic() - streamer.started)
            if i > last and i + 1 < len(STAGE_PROGRESS):  # a stage produced output: report the next one as running
                last = i
                set_step(ec, STAGE_PROGRESS[i][0], "done", _step_detail(ev))
                set_step(ec, STAGE_PROGRESS[i + 1][0], "running")
                await report_progress(ec, STAGE_PROGRESS[i + 1][1], STAGE_PROGRESS[i][2])
        await streamer.finish()
        final = await runner.session_service.get_session(app_name=APP, user_id="pipeline", session_id=session.id)
        st = final.state
        gate = st.get("gate", {})
        for name, _, _ in STAGE_PROGRESS:  # a gated video skips the later stages
            step = next(x for x in ec.steps if x["key"] == name)
            if step["status"] in ("pending", "running"):
                step["status"] = "skipped" if gate.get("skip") and name != "ingest_gate" else "done"
        await report_progress(ec, "Done" if not gate.get("skip") else "Skipped", 100)
        result = {"episode_id": episode_id, "status": "skipped" if gate.get("skip") else "published",
                  "skip_reason": gate.get("reason"), "statement_counts": st.get("statement_counts"),
                  "cost_usd": round(ec.budget.spent_usd, 4), "guardrail_events": [e.model_dump() for e in ec.events]}
        if result["status"] == "published" and settings.auto_sources:
            # The statements are already on screen. Now look up sources for the claims, each appearing as it finishes.
            from .sources import run_video_sources
            try:
                result["sources"] = await run_video_sources(episode_id, settings=settings, store=store)
            except Exception:
                log.exception("automatic source lookup crashed for %s", episode_id)
        return result
    except Exception as e:
        if is_budget_error(e):
            reason = f"Stopped by the per-video cost cap (${settings.max_cost_usd_per_episode:.2f})."
            await store.update_episode(episode_id, {"status": "failed", "skip_reason": reason})
            await store.save_guardrail_events(episode_id, ec.events)
            return {"episode_id": episode_id, "status": "failed", "reason": reason}
        log.exception("episode %s failed", episode_id)
        await store.update_episode(episode_id, {"status": "failed", "skip_reason": f"{type(e).__name__}: {e}"[:500]})
        await store.save_guardrail_events(episode_id, ec.events)
        return {"episode_id": episode_id, "status": "failed", "reason": f"{type(e).__name__}: {e}"}
    finally:
        try:
            token.var.reset(token)
        except ValueError:
            pass
