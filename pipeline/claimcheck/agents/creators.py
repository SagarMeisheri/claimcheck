"""A creator profile for a channel that isn't on the curated list: one web search and one model call, like a speaker's.

The row is saved (creators.source = 'web_search', no rank) so every later video from the channel reuses it. A channel the
search can't describe is saved with profile.identified = false, so it isn't searched again and nothing is guessed about
it. The profile comes only from the search excerpts and the neutral fields are what viewers see; the criticism notes
steer source searches only, like the curated profiles.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from typing import Any, Optional

from google.adk.runners import InMemoryRunner
from google.genai import types

from ..context import get_context, is_budget_error
from ..policy import domain_of
from ..profiles import usable_creator
from ..schemas import CreatorProfileOut
from ..tools.evidence import search_sources

log = logging.getLogger("claimcheck")
APP = "claimcheck_creators"


def _clip(text: str, n: int) -> str:
    return " ".join((text or "").split())[:n]


def creator_row(meta: dict[str, Any], out: Optional[CreatorProfileOut]) -> dict[str, Any]:
    """The creators row for a channel: the profile when the search identified it, an 'identified: false' marker when not."""
    channel = _clip(meta.get("channel_title") or "", 120) or "Unknown channel"
    base = {"podcast": channel, "youtube_channel_name": channel, "youtube_handles": [channel],
            "youtube_channel_ids": [meta.get("channel_id")], "market": "global", "country": "Unknown", "source": "web_search"}
    if out is None or not out.identified or not (out.summary.strip() or out.hosts.strip() or out.known_for.strip()):
        return {**base, "summary": None, "profile": {"identified": False}}
    profile = {k: v for k, v in {
        "hosts": _clip(out.hosts, 200), "host_background": _clip(out.host_background, 160), "host_bio": _clip(out.host_bio, 500),
        "topics": [_clip(t, 60) for t in out.topics[:8] if t.strip()], "known_for": _clip(out.known_for, 400),
        "criticism": _clip(out.criticism, 500),
        "public_opinion": _clip(out.public_opinion, 600),
        "leaning": _clip(out.leaning, 300) if out.leaning_basis != "none" else "",
        "leaning_basis": out.leaning_basis if out.leaning.strip() and out.leaning_basis != "none" else "",
    }.items() if v}
    return {**base, "podcast": _clip(out.podcast, 120) or channel, "country": _clip(out.country, 60) or "Unknown",
            "summary": _clip(out.summary, 400) or None, "profile": profile}


async def _search(meta: dict[str, Any]) -> list[Any]:
    ec = get_context()
    s = ec.settings
    channel, title = meta.get("channel_title") or "", meta.get("title") or ""
    ec.budget.add(s.search_cost_usd)
    return await search_sources(
        channel, dataclasses.replace(s, excerpt_chars=700, sources_per_claim=5), ec.policy,
        objective=(f"What is the YouTube show or channel \"{channel}\"? Find who hosts it, what it covers, where it is based and "
                   f"its political leaning if any, and how the public and the press view it (praise and criticism). A video titled \"{title}\" was published on it."),
        extra_queries=[f"{channel} YouTube channel hosts", f"{channel} podcast about"], location=s.default_search_location)


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


async def profile_creator(meta: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Looks the channel up on the web and saves the result. Returns the creators row to use for this video, or None when
    the channel couldn't be described (or something failed: the video is analysed without a profile). Never raises."""
    ec = get_context()
    if not (meta.get("channel_id") and meta.get("channel_title")):
        return None
    try:
        found = await _search(meta)
        pages = [{"n": i + 1, "group": "SEARCH", "title": x.title, "site": domain_of(x.url), "text": x.excerpt}
                 for i, x in enumerate(found) if x.excerpt]
        out = None
        if pages:
            where = f"the YouTube channel {meta['channel_title']}, video \"{meta.get('title') or ''}\""
            out = await _write(meta["channel_title"], where, pages)
        row = await ec.store.save_creator(creator_row(meta, out))
        return usable_creator(row)
    except Exception as e:
        reason = "budget" if is_budget_error(e) else f"{type(e).__name__}: {e}"
        ec.log("creators", "profile_failed", "skipped", f"{meta.get('channel_title')}: {reason}"[:300])
        return None
