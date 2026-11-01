"""EpisodePipeline: the ADK app that turns one YouTube URL into a scorecard.

EpisodePipeline (SequentialAgent)
  IngestGate      code   metadata + input guardrails
  TriageAgent     LLM    worthiness, PESTLE mix, never-check share
  TriageGate      code   skip low-value / off-policy videos
  ExtractorAgent  LLM    agentic video -> tagged statements (factual claim, opinion, forecast, ...)
  ClaimFilter     code   cap, content policy in code, which statements are verifiable
  Publisher       code   the only writer (claims are verified later, on request: see on_demand.py)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from google.adk.agents import SequentialAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from ..config import Settings, get_settings
from ..context import Budget, EpisodeContext, is_budget_error, report_progress, set_context
from ..guardrails.budget import BudgetPlugin
from ..guardrails.input_checks import parse_video_id
from ..policy import load_policy
from ..store import make_store
from .llm_agents import extractor_agent, triage_agent
from .stages import ClaimFilter, IngestGate, Publisher, TriageGate

log = logging.getLogger("claimcheck")
APP = "claimcheck"


def build_stages(settings: Settings) -> list:
    """Fresh (unparented) stage agents, so they can be placed in the pipeline or in the adk web wrapper."""
    return [
        IngestGate(name="ingest_gate"),
        triage_agent(settings),
        TriageGate(name="triage_gate"),
        extractor_agent(settings),
        ClaimFilter(name="claim_filter"),
        Publisher(name="publisher"),
    ]


def build_pipeline(settings: Settings) -> SequentialAgent:
    return SequentialAgent(name="episode_pipeline", sub_agents=build_stages(settings))


# (agent name, label shown while it runs, % complete once it has finished)
STAGE_PROGRESS = [
    ("ingest_gate", "Checking the video details", 5),
    ("triage", "Judging whether the video is worth checking", 10),
    ("triage_gate", "Applying the checking rules", 12),
    ("extractor", "Reading the video and tagging statements", 85),
    ("claim_filter", "Applying the content policy", 92),
    ("publisher", "Saving results", 100),
]
_STAGE_INDEX = {name: i for i, (name, _, _) in enumerate(STAGE_PROGRESS)}


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

    from ..tools.youtube import fetch_metadata  # channel lookup decides the track before the run
    meta = await fetch_metadata(video_id, settings)
    channel = await store.get_channel(meta.get("channel_id", "")) if meta.get("channel_id") else None
    track = (channel or {}).get("track", "finance_health")
    episode_id = episode_id or await store.create_episode({
        "youtube_video_id": video_id, "channel_id": (channel or {}).get("id"), "title": meta.get("title"),
        "status": "queued", "submitted_by": submitted_by,
    })
    await store.update_episode(episode_id, {"status": "processing"})

    ec = EpisodeContext(episode_id=episode_id, video_id=video_id, track=track, settings=settings, policy=policy,
                        store=store, budget=Budget(cap_usd=settings.max_cost_usd_per_episode),
                        plugins_factory=make_plugins_factory(settings))
    token = set_context(ec)
    runner = InMemoryRunner(agent=build_pipeline(settings), app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="pipeline", state={
        "video_url": f"https://www.youtube.com/watch?v={video_id}", "episode_id": episode_id, "track": track,
    })
    try:
        await report_progress(ec, STAGE_PROGRESS[0][1], 2)
        last = -1
        async for ev in runner.run_async(user_id="pipeline", session_id=session.id,
                                         new_message=types.Content(role="user", parts=[types.Part(text="Check this episode.")])):
            i = _STAGE_INDEX.get(getattr(ev, "author", ""), -1)
            if i > last and i + 1 < len(STAGE_PROGRESS):  # a stage produced output: report the next one as running
                last = i
                await report_progress(ec, STAGE_PROGRESS[i + 1][1], STAGE_PROGRESS[i][2])
        final = await runner.session_service.get_session(app_name=APP, user_id="pipeline", session_id=session.id)
        st = final.state
        gate = st.get("gate", {})
        return {"episode_id": episode_id, "status": "skipped" if gate.get("skip") else "published",
                "skip_reason": gate.get("reason"), "tally": st.get("tally"), "not_checked": st.get("not_checked"),
                "pending_review": st.get("pending_review", 0), "cost_usd": round(ec.budget.spent_usd, 4),
                "guardrail_events": [e.model_dump() for e in ec.events]}
    except Exception as e:
        if is_budget_error(e):
            reason = f"Stopped by the per-episode cost cap (${settings.max_cost_usd_per_episode:.2f})."
            await store.update_episode(episode_id, {"status": "failed", "skip_reason": reason})
            await store.save_guardrail_events(episode_id, ec.events)
            return {"episode_id": episode_id, "status": "failed", "reason": reason}
        log.exception("episode %s failed", episode_id)
        await store.update_episode(episode_id, {"status": "failed", "skip_reason": f"{type(e).__name__}: {e}"[:500]})
        await store.save_guardrail_events(episode_id, ec.events)
        return {"episode_id": episode_id, "status": "failed", "reason": f"{type(e).__name__}: {e}"}
    finally:
        from contextvars import Token  # noqa: F401
        try:
            token.var.reset(token)
        except ValueError:
            pass
