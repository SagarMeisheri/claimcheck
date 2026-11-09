"""The podcast profile's TL;DRs: one short sentence for the whole video and for each section of its profile.

The profile shows a lot of tags (how the questions were asked, how they were answered, what kind of statements, what the pages found,
the flags, the people). This writes the sentence a reader scans instead of the chips. Code counts everything first (build_digest), so
every number in the sentences is exact; one model call then only writes the words (prompts.TLDR). It describes what was found and never
judges anyone.

  headline, questions, answers, statements, evidence, flags   one sentence each
  people                                                       one sentence per speaker and for the show

Saved inside episodes.interaction.tldr (see Interaction in web/lib/types.ts), with `counts` (the answers and the evidence tallies it was
written from) so the page can say when answers were checked after it was written. Written after a video's sources are looked up, and again
after one answer is re-checked. It is best-effort: a failure leaves the page as it was, and is never raised into a lookup.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from ..context import get_context, is_budget_error
from ..guardrails.injection import screen_text, wrap_untrusted
from ..schemas import TldrOut

log = logging.getLogger("claimcheck")

MAX_ITEMS = 6      # contradicted answers listed in the digest
MAX_PEOPLE = 8
SENTENCE_CHARS = 320
HEADLINE_CHARS = 380
VERDICTS = ("contradicted", "ungrounded", "partly", "plausible", "grounded", "exempt")


def _clean(text: Any, n: int) -> str:
    return " ".join(screen_text(str(text or ""))[0].split())[:n]


def _clock(s: Any) -> str:
    s = int(s or 0)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _tally(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        if v:
            out[v] = out.get(v, 0) + 1
    return out


def counts_of(claims: list[dict[str, Any]]) -> dict[str, int]:
    """What the TL;DRs are written from, so the page can tell when answers have been checked since: the answers, and each verdict."""
    rows = [c for c in claims if c.get("question") and c.get("not_checked_reason") != "outside_policy"]
    out = {"answers": len(rows)}
    for v in VERDICTS:
        out[v] = sum(1 for c in rows if (((c.get("qa_tags") or {}).get("grounding") or {}).get("label")) == v)
    return out


def _person(label: str, role: str, name: str, about: str, incentives: dict[str, Any], profile: dict[str, Any], answers: int) -> dict[str, Any]:
    stakes = [{"tag": k.replace("_", " "), "why": _clean(v.get("reason"), 200)} for k, v in (incentives or {}).items() if isinstance(v, dict) and k != "access_preserving"]
    return {"label": label, "role": role, "name": _clean(name, 80), "about": _clean(about, 200), "answers": answers, "stakes": stakes[:5],
            "businesses": [_clean(b.get("name"), 60) for b in (profile.get("businesses") or [])[:4]],
            "criticism_reported": len(profile.get("critiques") or []) + len(profile.get("controversy_reports") or []) + len(profile.get("bias_claims") or [])}


def unchallenged(rows: list[dict[str, Any]]) -> list[str]:
    """Times of opinions that rest on an unverified premise (an anchored opinion the pages neither back nor contradict) and that the host's
    next question doesn't push back on. The same pattern the page shows (web/lib/indicators.ts)."""
    groups: list[list[dict[str, Any]]] = []
    for c in rows:
        if groups and groups[-1][0]["question"] == c["question"]:
            groups[-1].append(c)
        else:
            groups.append([c])
    out: list[str] = []
    for i, g in enumerate(groups):
        nxt = next((((x[0].get("question_analysis") or {}).get("type")) for x in groups[i + 1:] if x[0].get("question_kind") != "implied"), None)
        for c in g:
            t = c.get("qa_tags") or {}
            if (t.get("claim") or {}).get("type") == "anchored_opinion" and (t.get("grounding") or {}).get("label") in ("plausible", "partly", "ungrounded") and nxt and nxt != "challenging":
                out.append(_clock(c.get("start_s")))
    return out


def build_digest(ep: dict[str, Any], claims: list[dict[str, Any]], speakers: list[dict[str, Any]], creator: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Everything the TL;DRs may say, counted in code: tallies of every tag, the contradicted answers, the flags, and the people."""
    rows = sorted([c for c in claims if c.get("question") and c.get("not_checked_reason") != "outside_policy"], key=lambda c: c.get("start_s") or 0)
    questions, last = [], None
    for c in rows:  # one entry per distinct asked question
        if c.get("question_kind") == "implied" or c["question"] == last:
            last = c["question"]
            continue
        last = c["question"]
        t = (c.get("question_analysis") or {}).get("type")
        if t and t != "unclear":
            questions.append(t)
    tags = [c.get("qa_tags") or {} for c in rows]
    flagged: list[dict[str, Any]] = []
    for c, t in zip(rows, tags):
        g = (t.get("grounding") or {})
        if g.get("label") in ("contradicted", "ungrounded"):
            con = g.get("contradiction") or {}
            flagged.append({"time": _clock(c.get("start_s")), "verdict": g["label"], "question": _clean(c["question"], 160),
                            "said": _clean(con.get("said") or c.get("claim_text"), 200),
                            "difference": _clean(con.get("difference") or (g.get("basis") or [{}])[0].get("finding"), 220)})
    flagged.sort(key=lambda x: x["verdict"] != "contradicted")
    flags = _tally(f for t in tags for f in (t.get("flags") or []))
    people = [_person(x["label"], x.get("role") or "speaker", ((x.get("speakers") or {}).get("name")) or x["label"],
                      ((x.get("speakers") or {}).get("public_profile") or {}).get("role") or (x.get("speakers") or {}).get("summary") or "",
                      x.get("incentives") or {}, ((x.get("speakers") or {}).get("public_profile") or {}), int(x.get("statements") or 0))
              for x in sorted(speakers, key=lambda x: (x.get("role") != "host", -(x.get("statements") or 0)))][:MAX_PEOPLE]
    if creator:
        pp = creator.get("public_profile") or {}
        people.append(_person("__show", "show", creator.get("podcast") or "the show", pp.get("known_for") or creator.get("summary") or "", pp.get("incentives") or {}, pp, 0))
    return {
        "video": _clean(ep.get("title"), 160), "answers": len(rows), "interview_dynamic": (ep.get("interaction") or {}).get("dynamic") or "unknown",
        "question_types": _tally(questions), "answer_types": _tally((t.get("answer") or {}).get("type") for t in tags),
        "statement_types": _tally(c.get("statement_type") for c in rows),
        "evidence": _tally((t.get("grounding") or {}).get("label") for t in tags),
        "contradicted_or_ungrounded": flagged[:MAX_ITEMS],
        "conflicts_of_interest": sum(1 for t in tags if t.get("conflict")), "stakes_found": sum(1 for t in tags if t.get("stake")),
        "undisclosed": sum(1 for t in tags if (t.get("conflict") or {}).get("disclosure") == "undisclosed"),
        "flags": flags, "unchallenged_opinions_at": unchallenged(rows)[:MAX_ITEMS], "people": people,
    }


async def _generate(digest: dict[str, Any]) -> Optional[TldrOut]:
    """The call itself. A seam for tests."""
    from .llm_agents import tldr_agent
    from .research import _run_agent

    ec = get_context()
    state = {"digest": wrap_untrusted("DIGEST", json.dumps(digest, ensure_ascii=False, indent=1))}
    return await _run_agent(tldr_agent(ec.settings, name=f"tldr_{uuid.uuid4().hex[:6]}"), state, "tldr", TldrOut)


def check(out: Optional[TldrOut], digest: dict[str, Any], counts: dict[str, int]) -> Optional[dict[str, Any]]:
    """The sentences kept: every section needs one; a person's line is kept only for a label that was in the digest."""
    if out is None:
        return None
    sections = {k: _clean(getattr(out, k), HEADLINE_CHARS if k == "headline" else SENTENCE_CHARS) for k in ("headline", "questions", "answers", "statements", "evidence", "flags")}
    if not all(sections.values()):
        return None
    labels = {p["label"] for p in digest["people"]}
    people = {p.label: _clean(p.tldr, SENTENCE_CHARS) for p in out.people if p.label in labels and _clean(p.tldr, SENTENCE_CHARS)}
    return {**sections, "people": people, "counts": counts, "generated_at": datetime.now(timezone.utc).isoformat()}


async def make_tldr(store: Any, episode_id: str) -> Optional[dict[str, Any]]:
    """The TL;DRs for one video, from what is stored now. Needs an EpisodeContext (the call is metered). Returns None when there is
    nothing to summarise or the call failed; a budget error is raised."""
    ep = await store.get_episode(episode_id)
    claims = await store.list_claims_for_tldr(episode_id)
    if not ep or not any(c.get("question") for c in claims):
        return None
    speakers = await store.get_episode_speakers(episode_id)
    creator = await store.get_creator(ep.get("creator_id") or "")
    digest = build_digest(ep, claims, speakers, creator)
    try:
        out = await _generate(digest)
    except Exception as e:
        if is_budget_error(e):
            raise
        get_context().log("tldr", "tldr_failed", "skipped", f"{type(e).__name__}: {e}"[:200])
        log.warning("tldr failed: %s: %s", type(e).__name__, e)
        return None
    return check(out, digest, counts_of(claims))


async def save_tldr(store: Any, episode_id: str, tldr: dict[str, Any]) -> None:
    """Puts the TL;DRs into episodes.interaction, next to what is already there (the dynamic, the description notes)."""
    ep = await store.get_episode(episode_id)
    await store.update_episode(episode_id, {"interaction": {**((ep or {}).get("interaction") or {}), "tldr": tldr}})


async def refresh_tldr(store: Any, episode_id: str) -> None:
    """After answers are checked: write the TL;DRs again. Best-effort: never raises, skips when it is off or the budget has no room."""
    ec = get_context()
    s = ec.settings
    if not s.tldr or ec.budget.spent_usd + s.tldr_cost_estimate_usd > ec.budget.cap_usd:
        return
    try:
        tldr = await make_tldr(store, episode_id)
        if tldr:
            await save_tldr(store, episode_id, tldr)
    except Exception as e:  # a budget error too: the lookups that were just saved stand
        log.warning("could not refresh the TL;DRs for %s: %s: %s", episode_id, type(e).__name__, e)
