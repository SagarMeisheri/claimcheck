"""Dev entry point for `adk web`: paste a YouTube URL in the chat and watch the real pipeline run.

Start it with:  cd pipeline && adk web adk_app
It does the same setup as run_episode() (metadata, channel lookup, episode row, run context),
then hands over to the normal EpisodePipeline stages. Results are written to the same database.

Limits: failures are not recorded on the episode row the way run_episode() does, and each claim's
verification runs in its own isolated inner session, so it shows as one ClaimFanOut step here.
"""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from claimcheck.agents.pipeline import build_stages, make_plugins_factory
from claimcheck.config import get_settings
from claimcheck.context import Budget, EpisodeContext, set_context
from claimcheck.guardrails.input_checks import parse_video_id
from claimcheck.policy import load_policy
from claimcheck.store import make_store
from claimcheck.tools.youtube import fetch_metadata

_settings = get_settings()


def _say(agent: BaseAgent, ctx: InvocationContext, text: str, delta: dict | None = None, stop: bool = False) -> Event:
    return Event(author=agent.name, invocation_id=ctx.invocation_id,
                 actions=EventActions(state_delta=delta or {}, escalate=True if stop else None),
                 content=types.Content(role="model", parts=[types.Part(text=text)]))


class UiSetup(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        text = " ".join(p.text or "" for p in (ctx.user_content.parts if ctx.user_content else []))
        video_id = parse_video_id(text.strip().split()[0]) if text.strip() else None
        if not video_id:
            yield _say(self, ctx, "Send a YouTube video URL, e.g. https://www.youtube.com/watch?v=VIDEO_ID", {"gate": {"skip": True}}, stop=True)
            return
        store = make_store(_settings)
        meta = await fetch_metadata(video_id, _settings)  # the one YouTube Data API call for this video
        channel = await store.get_channel(meta.get("channel_id", "")) if meta.get("channel_id") else None
        track = (channel or {}).get("track", "finance_health")
        episode_id = await store.create_episode({
            "youtube_video_id": video_id, "channel_id": (channel or {}).get("id"), "title": meta.get("title"),
            "status": "queued", "submitted_by": "adk-web",
        })
        await store.update_episode(episode_id, {"status": "processing"})
        ec = EpisodeContext(episode_id=episode_id, video_id=video_id, track=track, settings=_settings, policy=load_policy(),
                            store=store, budget=Budget(cap_usd=_settings.max_cost_usd_per_episode),
                            plugins_factory=make_plugins_factory(_settings))
        set_context(ec)
        yield _say(self, ctx, f"Checking {video_id} (track: {track}, cost cap ${_settings.max_cost_usd_per_episode:.2f}). Episode {episode_id}.", {
            "video_url": f"https://www.youtube.com/watch?v={video_id}", "episode_id": episode_id, "track": track})


root_agent = SequentialAgent(name="claimcheck_ui", sub_agents=[UiSetup(name="ui_setup"), *build_stages(_settings)])
