"""A creator (show) profile from the web: searches and one model call, like a speaker's, version 2.

Searches cover who hosts and owns the show, what it covers, its sponsors and funding, and how it is received (praise, criticism,
controversies, bias claims). The profile writer returns a cited profile and the show's incentive tags in the same call
(schemas.CreatorProfileOut). The row is saved (creators.source = 'web_search', no rank) so every later video from the channel reuses
it. A curated show, or one profiled before version 2, gets the v2 fields merged into its row the next time a new video meets it; the
curated fields stay. A channel the search can't describe is saved with profile.identified = false, so it isn't searched again.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import InMemoryRunner
from google.genai import types

from ..context import get_context, is_budget_error
from ..profiles import PROFILE_VERSION, extraction_context, needs_rebuild, usable_creator, v2_fields
from ..schemas import CreatorProfileOut

log = logging.getLogger("claimcheck")
APP = "claimcheck_creators"


def _clip(text: str, n: int) -> str:
    return " ".join((text or "").split())[:n]


def _now() -> str:
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc).isoformat()


def creator_row(meta: dict[str, Any], out: Optional[CreatorProfileOut], pages: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """The creators row for a channel: the profile when the search identified it, an 'identified: false' marker when not."""
    channel = _clip(meta.get("channel_title") or "", 120) or "Unknown channel"
    base = {"podcast": channel, "youtube_channel_name": channel, "youtube_handles": [channel],
            "youtube_channel_ids": [meta.get("channel_id")], "market": "global", "country": "Unknown", "source": "web_search",
            "profile_version": PROFILE_VERSION, "profiled_at": _now()}
    if out is None or not out.identified or not (out.summary.strip() or out.hosts.strip() or out.known_for.strip()):
        return {**base, "summary": None, "profile": {"identified": False}}
    profile = {k: v for k, v in {
        "hosts": _clip(out.hosts, 200), "host_background": _clip(out.host_background, 160), "host_bio": _clip(out.host_bio, 500),
        "topics": [_clip(t, 60) for t in out.topics[:8] if t.strip()], "known_for": _clip(out.known_for, 400),
        **v2_fields(out, pages or []),
    }.items() if v}
    return {**base, "podcast": _clip(out.podcast, 120) or channel, "country": _clip(out.country, 60) or "Unknown",
            "summary": _clip(out.summary, 400) or None, "profile": profile}


async def _search(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Numbered pages about the show from three searches (who and what, how it is received, sponsors and money)."""
    from .speakers import search_pages

    channel, title = meta.get("channel_title") or "", meta.get("title") or ""
    where = f'A video titled "{title}" was published on it.'
    pages, _ = await search_pages([
        (channel, f'What is the YouTube show or channel "{channel}"? Find who hosts it, who owns, funds or distributes it, what it '
                  f"covers and where it is based. {where}", [f"{channel} YouTube channel hosts", f"{channel} podcast about"]),
        (f"{channel} criticism", f'How do the press and the public view "{channel}"? Find praise, criticism, controversies, '
                                 f"accusations of bias or of being soft on guests, and its political leaning. {where}",
         [f"{channel} controversy", f"{channel} bias"]),
        (f"{channel} sponsors", f'Who sponsors or advertises on "{channel}", and what paid partnerships or investors does it have?',
         [f"{channel} sponsored by", f"{channel} funding investors"]),
    ])
    return pages


async def _write(channel: str, where: str, pages: list[dict[str, Any]]) -> Optional[CreatorProfileOut]:
    from .llm_agents import creator_profiler_agent

    ec = get_context()
    runner = InMemoryRunner(agent=creator_profiler_agent(ec.settings, name=f"creator_profiler_{uuid.uuid4().hex[:6]}"),
                            app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="creators", state={
        "channel_name": channel, "appearance": where, "pages": pages})
    msg = types.Content(role="user", parts=[types.Part(text="Write the profile.")])
    async for _ in runner.run_async(user_id="creators", session_id=session.id, new_message=msg):
        pass
    done = await runner.session_service.get_session(app_name=APP, user_id="creators", session_id=session.id)
    raw = done.state.get("profile")
    return CreatorProfileOut.model_validate(raw) if raw else None


async def profile_creator(meta: dict[str, Any], existing: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Looks the channel up on the web and saves the result. `existing`: a curated or older row to bring up to version 2 (its own
    fields are kept). Returns the creators row to use for this video, or None when the channel couldn't be described (or something
    failed: the video is analysed with whatever row it had). Never raises."""
    ec = get_context()
    if not (meta.get("channel_id") and meta.get("channel_title")):
        return usable_creator(existing)
    try:
        pages = await _search(meta)
        out = None
        if pages:
            where = f"the YouTube channel {meta['channel_title']}, video \"{meta.get('title') or ''}\""
            out = await _write(meta["channel_title"], where, pages)
        row = creator_row(meta, out, pages)
        if existing:
            if (row.get("profile") or {}).get("identified") is False:
                row = await ec.store.update_creator(existing["id"], {"profile_version": PROFILE_VERSION, "profiled_at": row["profiled_at"]})
            else:
                merged = {**(existing.get("profile") or {}), **{k: v for k, v in row["profile"].items() if k not in ("hosts",) or not (existing.get("profile") or {}).get(k)}}
                row = await ec.store.update_creator(existing["id"], {"profile": merged, "summary": existing.get("summary") or row.get("summary"),
                                                                    "profile_version": PROFILE_VERSION, "profiled_at": row["profiled_at"]})
        else:
            row = await ec.store.save_creator(row)
        return usable_creator(row)
    except Exception as e:
        reason = "budget" if is_budget_error(e) else f"{type(e).__name__}: {e}"
        ec.log("creators", "profile_failed", "skipped", f"{meta.get('channel_title')}: {reason}"[:300])
        return usable_creator(existing)


def creator_needs_profile(saved: Optional[dict[str, Any]]) -> bool:
    """A channel never looked up, or a show whose profile is older than version 2 (or stale)."""
    return saved is None or needs_rebuild(saved)


async def resolve_creator(meta: dict[str, Any]) -> tuple[Optional[dict[str, Any]], bool]:
    """The show's profile for this video: curated, cached, or from the web. (creator, built from the web now). Sets ec.creator and the
    episode's creator_id. Never raises."""
    ec = get_context()
    saved = None
    try:
        saved = await ec.store.get_creator_by_channel(meta.get("channel_id") or "")
    except Exception:
        log.exception("creator lookup failed for %s", meta.get("channel_id"))
    creator = usable_creator(saved)
    built = False
    if ec.settings.profile_creators and creator_needs_profile(saved):
        creator = await profile_creator(meta, existing=saved)
        built = creator is not None
    ec.creator = creator
    if creator:
        await ec.store.update_episode(ec.episode_id, {"creator_id": creator["id"]})
    return creator, built


class CreatorProfiler(BaseAgent):
    """The show's profile as a stage of its own. Not in the pipeline any more: PeopleProfiler resolves the show as the first part of
    its one profiling step (agents/people.py); this stays for running the show step alone."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        st = ctx.session.state
        text = "skipped"
        if not st.get("gate", {}).get("skip"):
            creator, found = await resolve_creator(st.get("metadata") or {})
            text = (f"{creator['podcast']} (profiled from the web)" if found else creator["podcast"]) if creator else "No profile for this channel"
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
                    actions=EventActions(state_delta={"creator_context": extraction_context(get_context().creator)}),
                    content=types.Content(role="model", parts=[types.Part(text=text)]))
