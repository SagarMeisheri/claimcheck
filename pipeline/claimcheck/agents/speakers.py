"""SpeakerProfiler: a pipeline step that gives every named speaker in a video a profile, reused across videos.

For each speaker label the extractor used (claims.speaker), most statements first:
  role label ('Host', 'Guest 1')   no profile; recorded with its role
  a host of the matched creator    profile written from the creator's own profile (no search)
  already in `speakers`            reused as is
  new name                         one Parallel search ("who is X", with the video's title, channel and subjects so
                                   the search can tell people with the same name apart), then one model call
                                   (prompts.PROFILE_SPEAKER) that writes the profile from the excerpts only, or says
                                   the excerpts don't clearly describe one public person (saved as 'not_found')
At most settings.max_speaker_profiles new profiles per video, a few at a time. Everything is charged to the video's
budget; a failure leaves that speaker without a profile and never fails the video.

The profiles give later steps context (agents/sources.py): what a speaker is known for steers the searches. Their
known positions and criticisms are never shown to viewers.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from collections import Counter
from typing import Any, AsyncGenerator, Optional

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import InMemoryRunner
from google.genai import types

from ..context import get_context, is_budget_error
from ..policy import domain_of
from ..profiles import host_groups, is_role_label, match_host, name_key, search_location
from ..schemas import ClaimRecord, SpeakerProfileOut
from ..tools.evidence import search_sources

log = logging.getLogger("claimcheck")
APP = "claimcheck_speakers"
PROFILE_CONCURRENCY = 3


def role_of(label: str) -> Optional[str]:
    low = (label or "").lower()
    if "host" in low or "anchor" in low or "interviewer" in low or "moderator" in low:
        return "host"
    if "guest" in low or "interviewee" in low or "panel" in low:
        return "guest"
    return None


def host_profile(host: str, creator: dict[str, Any]) -> dict[str, Any]:
    """A speakers row for a show's host, from the creator profile (no search)."""
    p = creator.get("profile") or {}
    podcast = creator.get("podcast") or ""
    bio = p.get("host_bio") or p.get("host_background") or ""
    return {
        "name": host, "name_key": name_key(host), "status": "ready", "creator_id": creator.get("id"),
        "summary": _host_summary(host, creator),
        "profile": {k: v for k, v in {"role": f"Host of {podcast}", "background": bio, "topics": p.get("topics") or [],
                                      "known_positions": p.get("biases"), "criticisms": p.get("criticism")}.items() if v},
        "sources": [],
    }


def _host_summary(host: str, creator: dict[str, Any]) -> str:
    """'Host of Breaking Points, with Krystal Ball.' The show's bio describes all hosts together, so it isn't used here."""
    others = [g[-1] for g in host_groups(creator) if host not in g]
    podcast = creator.get("podcast") or "the show"
    return f"Host of {podcast}" + (f", with {', '.join(others[:3])}" if others else "") + "."


def appearance(meta: dict[str, Any], topics: list[str]) -> str:
    title, channel = meta.get("title") or "", meta.get("channel_title") or ""
    where = f"the YouTube video \"{title}\"" + (f" on the channel {channel}" if channel else "")
    return where + (f", speaking about {', '.join(topics[:5])}" if topics else "")


async def build_profile(label: str, meta: dict[str, Any], topics: list[str]) -> dict[str, Any]:
    """One search and one model call -> a speakers row ('ready' or 'not_found'). Raises on search or model errors."""
    from .llm_agents import speaker_profiler_agent

    ec = get_context()
    s = ec.settings
    where = appearance(meta, topics)
    ec.budget.add(s.search_cost_usd)
    found = await search_sources(
        label, dataclasses.replace(s, excerpt_chars=700, sources_per_claim=5), ec.policy,
        objective=(f"Who is {label}? Find their profession, current role, organisations, public positions and notable "
                   f"criticisms. They appeared in {where}."),
        extra_queries=[f"{label} biography", f"{label} {' '.join(topics[:2])}"], location=search_location(ec.creator, s.default_search_location))
    row: dict[str, Any] = {"name": label, "name_key": name_key(label), "status": "not_found", "summary": None,
                           "profile": {}, "sources": [{"url": x.url, "title": x.title} for x in found[:5]]}
    pages = [{"n": i + 1, "group": "SEARCH", "title": x.title, "site": domain_of(x.url), "text": x.excerpt}
             for i, x in enumerate(found) if x.excerpt]
    if not pages:
        return row
    runner = InMemoryRunner(agent=speaker_profiler_agent(s, name=f"speaker_profiler_{uuid.uuid4().hex[:6]}"),
                            app_name=APP, plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="speakers", state={
        "speaker_name": label, "appearance": where, "pages": pages})
    msg = types.Content(role="user", parts=[types.Part(text="Write the profile.")])
    async for _ in runner.run_async(user_id="speakers", session_id=session.id, new_message=msg):
        pass
    done = await runner.session_service.get_session(app_name=APP, user_id="speakers", session_id=session.id)
    raw = done.state.get("profile")
    out = SpeakerProfileOut.model_validate(raw) if raw else None
    if out is None or not out.identified or not out.summary.strip():
        return row
    clip = lambda t, n: " ".join((t or "").split())[:n]  # noqa: E731
    row.update(status="ready", summary=clip(out.summary, 400), profile={k: v for k, v in {
        "role": clip(out.role, 160), "background": clip(out.background, 500),
        "affiliations": [clip(a, 80) for a in out.affiliations[:8] if a.strip()],
        "topics": [clip(t, 60) for t in out.topics[:8] if t.strip()],
        "known_positions": clip(out.known_positions, 500), "criticisms": clip(out.criticisms, 500),
    }.items() if v})
    return row


async def profile_speakers(records: list[ClaimRecord], meta: dict[str, Any]) -> list[dict[str, Any]]:
    """episode_speakers rows for one video, creating speaker profiles as needed. Never raises."""
    ec = get_context()
    store, s = ec.store, ec.settings
    counts = Counter(r.claim.speaker.strip() for r in records
                     if r.not_checked_reason != "outside_policy" and (r.claim.speaker or "").strip())
    topics_by: dict[str, Counter] = {}
    for r in records:
        topics_by.setdefault((r.claim.speaker or "").strip(), Counter()).update(r.claim.topics or [])
    rows: list[dict[str, Any]] = []
    to_build: list[tuple[dict[str, Any], str]] = []
    for label, n in counts.most_common():
        row: dict[str, Any] = {"label": label, "statements": n, "speaker_id": None, "role": role_of(label)}
        rows.append(row)
        if is_role_label(label):
            # "Host" on a show with one host is that host: use their profile (context for the source searches too).
            groups = host_groups(ec.creator) if row["role"] == "host" else []
            if len(groups) == 1:
                try:
                    host = groups[0][-1]
                    sp = await store.get_speaker(name_key(host)) or await store.save_speaker(host_profile(host, ec.creator))
                    row["speaker_id"] = (sp or {}).get("id")
                except Exception:
                    log.exception("host lookup failed for %r", label)
            continue
        try:
            host = match_host(label, ec.creator)
            if host:
                key = name_key(host)
                sp = await store.get_speaker(key) or await store.save_speaker(host_profile(host, ec.creator))
                row.update(speaker_id=(sp or {}).get("id"), role="host")
                continue
            existing = await store.get_speaker(name_key(label))
            if existing:
                row["speaker_id"] = existing["id"] if existing.get("status") == "ready" else None
            elif s.profile_speakers and len(to_build) < s.max_speaker_profiles:
                to_build.append((row, label))
        except Exception:
            log.exception("speaker lookup failed for %r", label)
        row["role"] = row["role"] or "guest"

    gate = asyncio.Semaphore(PROFILE_CONCURRENCY)

    async def one(row: dict[str, Any], label: str) -> None:
        async with gate:
            if ec.budget.spent_usd + s.search_cost_usd > ec.budget.cap_usd:
                return
            try:
                topics = [t.replace("_", " ") for t, _ in topics_by.get(label, Counter()).most_common(4)]
                sp = await store.save_speaker(await build_profile(label, meta, topics))
                if sp and sp.get("status") == "ready":
                    row["speaker_id"] = sp["id"]
            except Exception as e:
                reason = "budget" if is_budget_error(e) else f"{type(e).__name__}: {e}"
                ec.log("speakers", "profile_failed", "skipped", f"{label}: {reason}"[:300])

    await asyncio.gather(*(one(r, label) for r, label in to_build))
    return rows


class SpeakerProfiler(BaseAgent):
    """Pipeline step after the content policy: profiles for the named speakers, and who speaks in the video."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        ec = get_context()
        st = ctx.session.state
        rows: list[dict[str, Any]] = []
        if not st.get("gate", {}).get("skip"):
            records = [ClaimRecord.model_validate(r) for r in st.get("claim_records", [])]
            try:
                rows = await profile_speakers(records, st.get("metadata") or {})
                await ec.store.save_episode_speakers(ec.episode_id, rows)
            except Exception:
                log.exception("speaker profiles failed for %s", ec.episode_id)
        named = sum(1 for r in rows if r.get("speaker_id"))
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
                    actions=EventActions(state_delta={"speaker_rows": rows}),
                    content=types.Content(role="model", parts=[types.Part(text=f"{named} of {len(rows)} speakers have a profile")]))
