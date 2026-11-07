"""Who appears in a video, found before extraction, then profiled and tagged (pipeline stage PeopleProfiler).

  1. the show's hosts (the creator profile) and the people the description lists (description.parse_people): code only
  2. one model call (prompts.PEOPLE, schemas.PeopleOut) over the title and the whole description, link lines included: the
     description is where creators introduce their guests and link what they sell. Only when that names no guest: one web search
     on the title and channel, and the call again with its excerpts. A name the model returns is kept only if it appears in that
     text: nothing is guessed. What the description promotes for a person (their book, company, course) is kept with them.
  3. each person's profile from the speakers cache, else the web, steered by how the description introduces them
     (agents/speakers.prepare_people), and their incentive tags from the profile plus, for this video, what its description
     promotes for them (agents/profile_tags.tag_rows)

The people found join ec.listed_people, so the extractor names speakers from them (stages.speaker_label), and their rows are saved to
episode_speakers straight away: the People tab fills before the first answer. Never fails the video.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from typing import Any, AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import InMemoryRunner
from google.genai import types

from ..context import get_context, is_budget_error
from ..description import people_context
from ..guardrails.injection import screen_text, wrap_untrusted
from ..policy import domain_of
from ..profiles import extraction_context, host_groups, is_role_label, name_key, search_location
from ..schemas import PeopleOut
from ..tools.evidence import search_sources
from .profile_tags import description_notes, tag_rows

log = logging.getLogger("claimcheck")
APP = "claimcheck_people"
MAX_PEOPLE = 8
DESCRIPTION_CHARS = 6000


def _in_text(name: str, text: str) -> bool:
    """Every word of the name appears in the source text (case-insensitive)."""
    words = name_key(name).split()
    low = name_key(text)
    return bool(words) and all(f" {w} " in f" {low} " for w in words)


def _promotes(p: dict[str, Any]) -> list[str]:
    return [" ".join(str(x).split())[:120] for x in (p.get("promotes") or []) if str(x).strip()][:6]


def merge_people(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per person (by name), the first group's role kept, hosts first."""
    out: dict[str, dict[str, Any]] = {}
    for g in groups:
        for p in g:
            name = " ".join((p.get("name") or "").split())[:80]
            if not name or is_role_label(name):
                continue
            key = name_key(name)
            if key in out:
                out[key]["is_host"] = out[key]["is_host"] or bool(p.get("is_host"))
                out[key]["role"] = out[key]["role"] or (p.get("role") or "")
                out[key]["promotes"] = list(dict.fromkeys(out[key]["promotes"] + _promotes(p)))[:6]
            else:
                out[key] = {"name": name, "role": " ".join((p.get("role") or "").split())[:160], "is_host": bool(p.get("is_host")),
                            "promotes": _promotes(p)}
    return sorted(out.values(), key=lambda p: not p["is_host"])[:MAX_PEOPLE]


async def _search(meta: dict[str, Any]) -> list[dict[str, Any]]:
    ec = get_context()
    s = ec.settings
    title, channel = meta.get("title") or "", meta.get("channel_title") or ""
    if ec.budget.spent_usd + s.search_cost_usd > ec.budget.cap_usd or not title:
        return []
    ec.budget.add(s.search_cost_usd)
    found = await search_sources(
        f"{title} {channel}"[:200], dataclasses.replace(s, excerpt_chars=500, sources_per_claim=6), ec.policy,
        objective=f'Who are the host and the guests in the video "{title}" on the YouTube channel "{channel}"?',
        extra_queries=[f"{title} guest", f"{channel} podcast episode guest"], location=search_location(ec.creator, s.default_search_location))
    return [{"n": i + 1, "site": domain_of(x.url), "title": x.title, "text": x.excerpt} for i, x in enumerate(found) if x.excerpt]


async def _ask(meta: dict[str, Any], pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from .llm_agents import people_finder_agent

    ec = get_context()
    page_text = "\n\n".join(wrap_untrusted(f"SEARCH PAGE {p['n']}", f"Title: {p['title']}\nSite: {p['site']}\nExcerpt: {screen_text(p['text'])[0]}")
                            for p in pages) or "(none)"
    state = {"video_title": wrap_untrusted("TITLE", meta.get("title") or ""), "channel_title": wrap_untrusted("CHANNEL", meta.get("channel_title") or ""),
             "creator_context": extraction_context(ec.creator), "pages": page_text,
             "description": wrap_untrusted("DESCRIPTION", screen_text((meta.get("description") or "")[:DESCRIPTION_CHARS])[0])}
    runner = InMemoryRunner(agent=people_finder_agent(ec.settings, name=f"people_finder_{uuid.uuid4().hex[:6]}"), app_name=APP,
                            plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="people", state=state)
    async for _ in runner.run_async(user_id="people", session_id=session.id,
                                    new_message=types.Content(role="user", parts=[types.Part(text="List the people.")])):
        pass
    done = await runner.session_service.get_session(app_name=APP, user_id="people", session_id=session.id)
    raw = done.state.get("people")
    out = PeopleOut.model_validate(raw) if raw else PeopleOut()
    source = " ".join([meta.get("title") or "", meta.get("description") or ""] + [p["text"] + " " + (p["title"] or "") for p in pages])
    return [p.model_dump() for p in out.people if _in_text(p.name, source)]


async def find_people(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Hosts, listed people and the people the model finds, merged. The model step's failure leaves the first two."""
    ec = get_context()
    hosts = [{"name": g[-1], "role": f"Host of {(ec.creator or {}).get('podcast') or 'the show'}", "is_host": True} for g in host_groups(ec.creator)]
    found: list[dict[str, Any]] = []
    try:
        found = await _ask(meta, [])  # the description first: no search
        if not any(not p.get("is_host") for p in found + list(ec.listed_people)):
            pages = await _search(meta)  # it names no guest: look the video up, and ask again with what the pages say
            if pages:
                found = await _ask(meta, pages)
    except Exception as e:
        if is_budget_error(e):
            raise
        ec.log("people", "people_finder_failed", "skipped", f"{type(e).__name__}: {e}"[:200])
    return merge_people(hosts, ec.listed_people, found)


def extractor_people(listed: list[dict[str, Any]], people: list[dict[str, Any]]) -> str:
    """The extractor's lines about who appears. The description's list stays strict (description.people_context: a speaker name must
    be one of them); people found otherwise are offered as names to use, never as the only names allowed."""
    text = people_context(listed)
    listed_keys = {name_key(p["name"]) for p in listed}
    extra = [p for p in people if name_key(p["name"]) not in listed_keys]
    if extra:
        lines = "\n".join(f"- {p['name']}" + (f": {p['role']}" if p.get("role") else "") for p in extra)
        text += ("\n" if text else "") + ("These people are also known to appear (from the show's profile and web pages):\n"
                                         + wrap_untrusted("KNOWN PEOPLE", lines)
                                         + "\nWhen you can tell one of them is speaking, use that exact name.")
    return text


class PeopleProfiler(BaseAgent):
    """Pipeline stage before the extractor: who appears, their profiles and their incentive tags."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from .speakers import db_row, prepare_people

        ec = get_context()
        st = ctx.session.state
        meta = st.get("metadata") or {}
        rows: list[dict[str, Any]] = []
        delta: dict[str, Any] = {}
        if not st.get("gate", {}).get("skip"):
            try:
                people = await find_people(meta)
                delta["people_context"] = extractor_people(ec.listed_people, people)
                ec.description_notes = description_notes(meta.get("description") or "", people)
                rows = await prepare_people(people, meta)
                tag_rows(rows, rows, ec.creator, ec.video_id)
                ec.prepared_speakers = {name_key(r["label"]): r for r in rows}
                await ec.store.save_episode_speakers(ec.episode_id, [db_row(r) for r in rows])
                await ec.store.update_episode(ec.episode_id, {"interaction": {"description_notes": ec.description_notes}})
            except Exception as e:
                if is_budget_error(e):
                    raise
                log.exception("people profiles failed for %s", ec.episode_id)
        named = sum(1 for r in rows if r.get("speaker_id"))
        tagged = sum(1 for r in rows if r.get("incentives") or r.get("incentives_internal"))
        yield Event(author=self.name, invocation_id=ctx.invocation_id, actions=EventActions(state_delta=delta),
                    content=types.Content(role="model", parts=[types.Part(
                        text=f"{named} of {len(rows)} people have a profile; {tagged} have incentive tags")]))
