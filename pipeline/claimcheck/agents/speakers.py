"""Speaker profiles: who each host and guest is, reused across videos. Two passes:

  before extraction  PeopleProfiler (agents/people.py finds who appears: the show's hosts, the description's people, a model over the
                     title, description and one search). Each is profiled here, then tagged (agents/profile_tags.py), so every
                     answer streamed by the extractor is read against its speaker's profile.
  after extraction   SpeakerProfiler: every label the extractor used. A label already profiled before is reused; anyone new is
                     profiled the same way, then tagged.

A profile (version 2) comes from web searches (who they are: expertise, roles, companies, investments, products; how they are
seen: praise, criticism, controversies, bias claims, political leaning; for a host also sponsors and ties to guests), then one
model call (prompts.PROFILE_SPEAKER) that writes a cited profile from the excerpts only, or says they don't clearly describe one
public person ('not_found'). The `speakers` table is the cache: a ready version-2 profile younger than PROFILE_MAX_AGE_DAYS is
reused with no search. At most settings.max_speaker_profiles new profiles per video. Everything is charged to the video's budget;
a failure leaves that speaker without a profile and never fails the video.
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
from ..profiles import PROFILE_VERSION, host_groups, is_role_label, match_host, name_key, needs_rebuild, search_location, v2_fields
from ..schemas import ClaimRecord, SpeakerProfileOut
from ..tools.evidence import search_sources

log = logging.getLogger("claimcheck")
APP = "claimcheck_speakers"
PROFILE_CONCURRENCY = 8  # everyone in the video at once (people.MAX_PEOPLE)


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


async def host_row(host: str, creator: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """A host's speakers row: the creator-profile basics, plus their own comprehensive profile from the web (the show's profile
    describes the show, not each host). A failed or budget-limited search leaves the plain row."""
    row = host_profile(host, creator)
    ec = get_context()
    s = ec.settings
    if not s.profile_speakers or ec.budget.spent_usd + s.search_cost_usd > ec.budget.cap_usd:
        return row
    try:
        found = await build_profile(host, meta, [], described_as=f"host of {creator.get('podcast') or 'the show'}", host=True)
    except Exception as e:
        ec.log("speakers", "host_profile_failed", "skipped", f"{host}: {type(e).__name__}: {e}"[:300])
        return row
    if found.get("status") == "ready":
        row["profile"] = {**row["profile"], **{k: v for k, v in found["profile"].items() if k != "role" and v}}
        row["summary"] = found.get("summary") or row["summary"]
        row["sources"] = found.get("sources") or []
    row.update(profile_version=PROFILE_VERSION, profiled_at=_now())
    return row


def _now() -> str:
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc).isoformat()


def appearance(meta: dict[str, Any], topics: list[str], described_as: str = "") -> str:
    title, channel = meta.get("title") or "", meta.get("channel_title") or ""
    where = f"the YouTube video \"{title}\"" + (f" on the channel {channel}" if channel else "")
    if described_as:  # what the video's description says they are, so the search finds the right person
        where += f", where the description introduces them as \"{described_as}\""
    return where + (f", speaking about {', '.join(topics[:5])}" if topics else "")


def described_profile(name: str, described_as: str) -> dict[str, Any]:
    """A speakers row from the video description alone, when the web search can't identify the person."""
    role = " ".join(described_as.split())[:160]
    return {"name": name, "name_key": name_key(name), "status": "ready", "summary": f"{role}.",
            "profile": {"role": role}, "sources": [], "profile_version": PROFILE_VERSION, "profiled_at": _now()}


PAGES_PER_SEARCH = 8
PROFILE_EXCERPT_CHARS = 900
MAX_PROFILE_PAGES = 24


def profile_searches(label: str, where: str, host: bool) -> list[tuple[str, str, list[str]]]:
    """(query, objective, extra queries) for each search a profile is written from."""
    out = [
        (label, f"Who is {label}? Find their profession, expertise and credentials, current and past roles, companies they founded, run "
                f"or own, investments and portfolio companies, board and advisory seats, funds, and products they sell (books, courses, "
                f"apps, services). They appeared in {where}.",
         [f"{label} biography career", f"{label} founder investor companies board", f"{label} expertise credentials"]),
        (f"{label} controversy", f"How is {label} viewed? Find praise and criticism from the press and the public, controversies, "
                                 f"accusations of bias or conflicts of interest, political leaning, party or government posts, donations "
                                 f"or campaign roles. They appeared in {where}.",
         [f"{label} criticism", f"{label} political views", f"{label} accused bias conflict of interest"]),
    ]
    if host:
        out.append((f"{label} podcast sponsors", f"What sponsors, paid partners and advertisers do {label}'s shows have, what does "
                                                 f"{label} invest in, and which guests or companies are they tied to?",
                    [f"{label} investments", f"{label} sponsored partnership"]))
    return out


async def search_pages(searches: list[tuple[str, str, list[str]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Runs the searches at once; returns (numbered pages for the profile writer, sources [{url, title}]). One URL once. A failed
    search is skipped; raises only if every one failed (or for the budget)."""
    ec = get_context()
    s = ec.settings
    settings = dataclasses.replace(s, excerpt_chars=PROFILE_EXCERPT_CHARS, sources_per_claim=PAGES_PER_SEARCH)
    loc = search_location(ec.creator, s.default_search_location)

    async def one(q: str, objective: str, extra: list[str]) -> Any:
        ec.budget.add(s.search_cost_usd)
        return await search_sources(q, settings, ec.policy, objective=objective, extra_queries=extra, location=loc)

    results = await asyncio.gather(*(one(*x) for x in searches), return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException) and is_budget_error(r):
            raise r
    ok = [r for r in results if not isinstance(r, BaseException)]
    if not ok:
        raise next(r for r in results if isinstance(r, BaseException))
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rank in range(max(len(r) for r in ok)):
        for r in ok:
            if rank < len(r) and r[rank].url not in seen and r[rank].excerpt and len(pages) < MAX_PROFILE_PAGES:
                seen.add(r[rank].url)
                x = r[rank]
                pages.append({"n": len(pages) + 1, "group": "SEARCH", "title": x.title, "site": domain_of(x.url), "url": x.url, "text": x.excerpt})
    return pages, [{"url": p["url"], "title": p["title"]} for p in pages[:10]]


async def build_profile(label: str, meta: dict[str, Any], topics: list[str], described_as: str = "", host: bool = False) -> dict[str, Any]:
    """Web searches and one model call -> a speakers row ('ready' or 'not_found'), version 2. Raises on search or model errors.
    A person the description introduces is never 'not_found': the description's role is their profile then."""
    from .llm_agents import speaker_profiler_agent

    ec = get_context()
    s = ec.settings
    where = appearance(meta, topics, described_as)
    pages, sources = await search_pages(profile_searches(label, where, host))
    row: dict[str, Any] = {"name": label, "name_key": name_key(label), "status": "not_found", "summary": None,
                           "profile": {}, "sources": sources, "profile_version": PROFILE_VERSION, "profiled_at": _now()}
    if not pages:
        return {**described_profile(label, described_as), "sources": sources} if described_as else row
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
        return {**described_profile(label, described_as), "sources": sources} if described_as else row
    clip = lambda t, n: " ".join((t or "").split())[:n]  # noqa: E731
    row.update(status="ready", summary=clip(out.summary, 400), profile={k: v for k, v in {
        "role": clip(out.role, 160) or clip(described_as, 160), "background": clip(out.background, 500),
        "affiliations": [clip(a, 80) for a in out.affiliations[:8] if a.strip()],
        "topics": [clip(t, 60) for t in out.topics[:8] if t.strip()],
        **v2_fields(out, pages),
    }.items() if v})
    return row


async def cached_or_build(label: str, meta: dict[str, Any], topics: list[str], described_as: str = "") -> tuple[Optional[dict[str, Any]], bool]:
    """(speakers row, built): the cached profile when it is current, else a new one saved to the cache. built is False for a cache hit."""
    store = get_context().store
    existing = await store.get_speaker(name_key(label))
    if existing and not needs_rebuild(existing):
        if existing.get("status") == "ready" or not described_as:
            return existing, False
    return await store.save_speaker(await build_profile(label, meta, topics, described_as)), True


DB_KEYS = ("label", "statements", "speaker_id", "role", "incentives", "incentives_internal")


def db_row(row: dict[str, Any]) -> dict[str, Any]:
    """An episode_speakers row as saved (the working row also carries the speakers row it maps to, under "speaker")."""
    return {k: row.get(k) for k in DB_KEYS if k in row}


async def host_speaker(host: str, meta: dict[str, Any]) -> Optional[dict[str, Any]]:
    """A host's cached profile, or a new one (from the creator profile and the web)."""
    ec = get_context()
    existing = await ec.store.get_speaker(name_key(host))
    if existing and existing.get("status") == "ready" and not needs_rebuild(existing):
        return existing
    return await ec.store.save_speaker(await host_row(host, ec.creator, meta))


async def prepare_people(people: list[dict[str, Any]], meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Before extraction: a profile for every person known to appear ([{name, role, is_host}]), from the cache or the web, a few at a
    time. Returns the working rows (label = the name, statements 0, "speaker" = the speakers row). Never raises, except for the budget."""
    ec = get_context()
    s = ec.settings
    gate = asyncio.Semaphore(PROFILE_CONCURRENCY)
    rows: list[dict[str, Any]] = [{"label": p["name"], "statements": 0, "speaker_id": None, "promotes": p.get("promotes") or [],
                                   "role": "host" if p.get("is_host") or match_host(p["name"], ec.creator) else "guest"} for p in people]

    async def one(row: dict[str, Any], person: dict[str, Any]) -> None:
        async with gate:
            if ec.budget.spent_usd + s.search_cost_usd > ec.budget.cap_usd:
                return
            try:
                host = match_host(row["label"], ec.creator)
                if host and ec.creator:
                    sp = await host_speaker(host, meta)
                elif not s.profile_speakers or ec.profiles_built >= s.max_speaker_profiles:
                    sp = await ec.store.get_speaker(name_key(row["label"]))
                    if not sp and person.get("role"):
                        sp = await ec.store.save_speaker(described_profile(row["label"], person["role"]))
                else:
                    sp, built = await cached_or_build(row["label"], meta, [], person.get("role") or "")
                    ec.profiles_built += int(built)
                if sp and sp.get("status") == "ready":
                    row.update(speaker_id=sp["id"], speaker=sp)
            except Exception as e:
                if is_budget_error(e):
                    raise
                ec.log("speakers", "profile_failed", "skipped", f"{row['label']}: {type(e).__name__}: {e}"[:300])

    await asyncio.gather(*(one(r, p) for r, p in zip(rows, people)))
    return rows


async def profile_speakers(records: list[ClaimRecord], meta: dict[str, Any]) -> list[dict[str, Any]]:
    """After extraction: the working rows for every label the extractor used, reusing the people profiled before extraction
    (ec.prepared_speakers) and profiling anyone new (cache, else web). People profiled before but never named by the extractor stay on the list with 0 statements. Never raises."""
    ec = get_context()
    s = ec.settings
    counts = Counter(r.claim.speaker.strip() for r in records
                     if r.not_checked_reason != "outside_policy" and (r.claim.speaker or "").strip())
    topics_by: dict[str, Counter] = {}
    for r in records:
        topics_by.setdefault((r.claim.speaker or "").strip(), Counter()).update(r.claim.topics or [])
    prepared: dict[str, dict[str, Any]] = dict(ec.prepared_speakers)
    listed = {name_key(p["name"]): p for p in ec.listed_people}
    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    to_build: list[tuple[dict[str, Any], str]] = []
    for label, n in counts.most_common():
        key = name_key(label)
        host = match_host(label, ec.creator)
        if is_role_label(label) and role_of(label) == "host" and len(host_groups(ec.creator)) == 1:
            host = host_groups(ec.creator)[0][-1]  # "Host" on a show with one host is that host
        hit = prepared.get(key) or (prepared.get(name_key(host)) if host else None)
        if hit:
            used.add(name_key(hit["label"]))
            rows.append({**hit, "label": label, "statements": n})
            continue
        lp = listed.get(key)
        row: dict[str, Any] = {"label": label, "statements": n, "speaker_id": None, "new": True,
                               "role": "host" if host else (("host" if lp["is_host"] else "guest") if lp else (role_of(label) or "guest"))}
        rows.append(row)
        if is_role_label(label) and not host:
            continue
        try:
            if host and ec.creator:
                sp = await host_speaker(host, meta)
                if sp and sp.get("status") == "ready":
                    row.update(speaker_id=sp["id"], speaker=sp)
            else:
                to_build.append((row, label))
        except Exception as e:
            if is_budget_error(e):
                break
            log.exception("host lookup failed for %r", label)
    rows += [{**r, "statements": 0} for k, r in prepared.items() if k not in used]

    gate = asyncio.Semaphore(PROFILE_CONCURRENCY)

    async def one(row: dict[str, Any], label: str) -> None:
        async with gate:
            if ec.budget.spent_usd + s.search_cost_usd > ec.budget.cap_usd:
                return
            try:
                described_as = (listed.get(name_key(label)) or {}).get("role", "")
                if not s.profile_speakers or ec.profiles_built >= s.max_speaker_profiles:
                    sp = await ec.store.get_speaker(name_key(label))
                    if not sp and described_as:
                        sp = await ec.store.save_speaker(described_profile(label, described_as))
                else:
                    topics = [t.replace("_", " ") for t, _ in topics_by.get(label, Counter()).most_common(4)]
                    sp, built = await cached_or_build(label, meta, topics, described_as)
                    ec.profiles_built += int(built)
                if sp and sp.get("status") == "ready":
                    row.update(speaker_id=sp["id"], speaker=sp)
            except Exception as e:
                reason = "budget" if is_budget_error(e) else f"{type(e).__name__}: {e}"
                ec.log("speakers", "profile_failed", "skipped", f"{label}: {reason}"[:300])

    await asyncio.gather(*(one(r, label) for r, label in to_build))
    return rows


class SpeakerProfiler(BaseAgent):
    """Pipeline step after the content policy: everyone the extractor named, profiled and tagged; who speaks in the video."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from .people import people_line
        from .profile_tags import tag_rows

        ec = get_context()
        st = ctx.session.state
        rows: list[dict[str, Any]] = []
        new: list[dict[str, Any]] = []
        if not st.get("gate", {}).get("skip"):
            records = [ClaimRecord.model_validate(r) for r in st.get("claim_records", [])]
            try:
                rows = await profile_speakers(records, st.get("metadata") or {})
                new = [r for r in rows if r.pop("new", False) and not is_role_label(r["label"])]
                tag_rows(rows, rows, ec.creator, ec.video_id)  # code only: the tags come with the profiles
                await ec.store.save_episode_speakers(ec.episode_id, [db_row(r) for r in rows])
                ec.prepared_speakers.update({name_key(r["label"]): r for r in rows if r.get("speaker_id")})
            except Exception:
                log.exception("speaker profiles failed for %s", ec.episode_id)
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
                    actions=EventActions(state_delta={"speaker_rows": [db_row(r) for r in rows]}),
                    content=types.Content(role="model", parts=[types.Part(text=people_line(new) if new else "No one new")]))
