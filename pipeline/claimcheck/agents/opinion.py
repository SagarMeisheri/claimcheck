"""Assessing an opinion: is it backed by sources, what do the governing side and the opposition say, and does the answer show slant?

Most answers in an interview are opinions, so a figure check isn't enough. For an opinion, advice or forecast (or any answer the
classifier calls contested) four agents work together; the web is always searched through the Parallel SDK:

  source agent    agents/research.py: the checkable premises of the answer and what independent pages say about each
  stance agent    in parallel with it: one neutral issue, the same kind of queries for the governing side and the opposition, the
                  pages read for what each says (its own statements first), every quote checked against its page
  bias agent      reads the answer against the speaker's and the show's cached profiles (agents/speakers.py, creators.py) plus the
                  two results above, and writes signals: stake, prior stance, camp match, one-sidedness, loaded wording... each
                  with a quote that code checks is really in the answer, the question, a profile or a finding
  judge           merges them into the short assessment a reader sees

Code checks evidence, not conclusions: quotes must exist, a lean needs numbered signals, verdict words are dropped. The judge decides
the labels. It never calls anyone dishonest, and a thin profile means "can't tell". Anything that fails here leaves the answer with
the research alone.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import date
from typing import Any, Optional

from ..context import get_context, is_budget_error
from ..guardrails.injection import wrap_untrusted
from ..policy import domain_of
from ..schemas import Assessment, BiasRead, PlanPoint, Source, StanceFinding, StancePlan, StanceReading
from .independence import EPISODE, split_sources
from .research import (PAGE_CHARS, Research, _fetch, _run_agent, _search, clean_queries, context_text, quote_in_page,
                       research_answer)

log = logging.getLogger("claimcheck")
CAMPS = ("ruling", "opposition")
OPINION_TYPES = {"opinion", "advice", "forecast"}
MAX_PER_CAMP = 2
PAGES_PER_CAMP = 2
MAX_SIGNALS = 6
STALE_YEARS = 6  # a position from a page older than this is not what a camp says now
# The assessment describes evidence; these words would be a verdict on a person or a claim, so text with them is dropped.
_VERDICT = re.compile(r"\b(true|false|lie[sd]?|lying|liars?|wrong|incorrect|misleading|fake|dishonest|corrupt|propaganda|fraud\w*)\b", re.I)
GROUNDING_WORDS = {"backed": "Backed by independent sources", "partly_backed": "Partly backed by independent sources",
                   "unverified": "No independent source found for it", "not_backed": "Independent sources give a different account", "value_judgement": "A value judgement: nothing to check"}


# --- Small checks (pure code) ---------------------------------------------------------------------

def wanted(settings: Any, route: str, statement_type: Optional[str]) -> bool:
    """Opinions, advice, forecasts and anything the classifier called contested get the full assessment."""
    return bool(settings.opinion_check and settings.research_sources and route != "skip"
                and (route == "contested" or statement_type in OPINION_TYPES))


def camps_for(policy: dict[str, Any], location: Optional[str]) -> dict[str, str]:
    """Who 'the governing side' and 'the opposition' are in the show's country: set in policy.yaml, never chosen by the model."""
    table = policy.get("politics") or {}
    c = table.get((location or "").lower()) or table.get("default") or {}
    return {"ruling": c.get("ruling") or "the governing party or coalition", "opposition": c.get("opposition") or "the main opposition parties"}


def has_verdict(text: str) -> bool:
    return bool(_VERDICT.search(text or ""))


def _clip(text: str, n: int) -> str:
    return " ".join((text or "").split())[:n]


def _too_old(published: Any) -> bool:
    m = re.match(r"(\d{4})", str(published or ""))
    return bool(m) and int(m.group(1)) < date.today().year - STALE_YEARS


def verify_stances(findings: list[StanceFinding], pages: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Each camp's positions: the quote must be in the page it names and the text must not grade anyone. At most MAX_PER_CAMP a camp."""
    out: dict[str, list[dict[str, Any]]] = {c: [] for c in CAMPS}
    dropped = 0
    for f in findings:
        pg = pages[f.page - 1] if 1 <= f.page <= len(pages) else None
        if (pg is not None and _too_old(pg.get("date"))) or (pg is None or f.camp not in out or len(out[f.camp]) >= MAX_PER_CAMP or not quote_in_page(f.quote, pg["text"])
                or has_verdict(f.stance) or not f.stance.strip()):
            dropped += 1
            continue
        out[f.camp].append({"stance": _clip(f.stance, 300), "quote": _clip(f.quote, 400), "who": _clip(f.who, 80), "url": pg["url"],
                            "site": pg["site"], "title": _clip(pg["title"], 160), "date": pg.get("date")})
    return out, dropped


def pick_stance_pages(groups: dict[str, list[Source]], per_camp: int = PAGES_PER_CAMP) -> list[Source]:
    """Pages for each camp in turn: its own statements are welcome (a party's site is a fair source for the party's position),
    the episode's own pages are not. At most two a site, none twice."""
    chosen: list[Source] = []
    per_site: dict[str, int] = {}
    taken: set[str] = set()
    for camp in CAMPS:
        n = 0
        for s in sorted(groups.get(camp, []), key=lambda s: s.rank - (2 if s.tier == 1 else 0)):
            site = domain_of(s.url)
            if s.url in taken or per_site.get(site, 0) >= 2 or n >= per_camp:
                continue
            chosen.append(s)
            taken.add(s.url)
            per_site[site] = per_site.get(site, 0) + 1
            n += 1
    return chosen


def profile_text(p: dict[str, Any], keys: tuple[str, ...]) -> str:
    """A profile as plain 'key: value' lines. The bias agent reads it and its quotes are checked against exactly this text."""
    return "\n".join(f"{k}: {p[k]}" for k in keys if p.get(k))


SPEAKER_KEYS = ("name", "role", "affiliations", "leaning", "leaning_basis", "public_opinion")
SHOW_KEYS = ("podcast", "hosts", "country", "leaning", "leaning_basis", "public_opinion")


def findings_text(research: Research) -> str:
    """What the sources said about each point, as lines the bias agent and the judge read."""
    lines = []
    for i, p in enumerate(research.points, 1):
        lines.append(f"{i}. {p['text']} -> {p['status']}")
        for f in p["findings"][:3]:
            lines.append(f"   - {f['site']} ({f['independence']}, {f['relation']}): {f['finding']} \"{f['quote']}\"")
    return "\n".join(lines) or "No point of the answer had an independent source."


def stances_text(camps: dict[str, str], stances: Optional[dict[str, list[dict[str, Any]]]]) -> str:
    lines = []
    for c in CAMPS:
        found = (stances or {}).get(c) or []
        lines.append(f"{camps[c]}: " + (" | ".join(f"{s['stance']} \"{s['quote']}\" ({s['site']})" for s in found) if found else "no public statement found"))
    return "\n".join(lines)


def verify_signals(signals: list[Any], corpus: list[str]) -> tuple[list[dict[str, Any]], int]:
    """A signal stands only if its quote is really in the answer, the question, a profile or a finding, and its text grades no one."""
    kept: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    dropped = 0
    for s in signals:
        key = (s.kind, " ".join(s.quote.lower().split()))
        if (key in seen or len(kept) >= MAX_SIGNALS or has_verdict(s.text) or not s.text.strip()
                or not any(quote_in_page(s.quote, c) for c in corpus)):
            dropped += 1
            continue
        seen.add(key)
        kept.append({"kind": s.kind, "text": _clip(s.text, 220), "quote": _clip(s.quote, 300)})
    return kept, dropped


def clean_assessment(a: Assessment, signals: list[dict[str, Any]], has_evidence: bool) -> dict[str, Any]:
    """The judge's output with the rules applied: a lean needs numbered signals, free text with verdict words is blanked, and
    stake or a speaker's record need a signal that shows it."""
    used = sorted({n for n in a.signals if 1 <= n <= len(signals)})
    bias, toward = a.bias, a.toward
    if bias in ("leans", "one_sided") and (not used or toward == "none"):
        bias, toward = "cant_tell", "none"
    if bias in ("balanced", "cant_tell"):
        toward = "none"
    kinds = {signals[n - 1]["kind"] for n in used}
    free = lambda t, n: "" if has_verdict(t) else _clip(t, n)  # noqa: E731
    evidence = a.evidence if has_evidence else "none"
    return {
        "bottom_line": free(a.bottom_line, 300), "grounding": a.grounding, "grounding_reason": free(a.grounding_reason, 260),
        "bias": bias, "toward": toward, "bias_reason": free(a.bias_reason, 300), "signals": used,
        "objection": free(a.objection, 220), "speaker_record": free(a.speaker_record, 220) if "prior_stance" in kinds else "",
        "stake": free(a.stake, 220) if "stake" in kinds else "", "evidence": evidence,
    }


# --- Steps that call out (kept apart so tests can replace them) ------------------------------------

async def _stance_plan(ctx: dict[str, Any], camps: dict[str, str]) -> Optional[StancePlan]:
    from .llm_agents import stance_planner_agent

    ec = get_context()
    state = {"ruling": camps["ruling"], "opposition": camps["opposition"], "question": wrap_untrusted("QUESTION", ctx.get("question") or "(not asked directly)"),
             "answer": wrap_untrusted("ANSWER", ctx["statement"]), "context": context_text(ctx)}
    return await _run_agent(stance_planner_agent(ec.settings, name=f"stance_planner_{uuid.uuid4().hex[:6]}"), state, "stance_plan", StancePlan)


async def _stance_read(issue: str, camps: dict[str, str], pages: list[dict[str, Any]]) -> list[StanceFinding]:
    from .llm_agents import stance_reader_agent

    ec = get_context()
    state = {"issue": issue, "ruling": camps["ruling"], "opposition": camps["opposition"],
             "pages": [{"n": i, "title": p["title"], "site": p["site"], "text": p["text"], "date": p.get("date"), "origin": "a website"}
                       for i, p in enumerate(pages, 1)]}
    out = await _run_agent(stance_reader_agent(ec.settings, name=f"stance_reader_{uuid.uuid4().hex[:6]}"), state, "stance_reading", StanceReading)
    return out.findings if out else []


async def _bias(state: dict[str, Any]) -> Optional[BiasRead]:
    from .llm_agents import bias_agent

    return await _run_agent(bias_agent(get_context().settings, name=f"bias_agent_{uuid.uuid4().hex[:6]}"), state, "bias_read", BiasRead)


async def _judge(state: dict[str, Any]) -> Optional[Assessment]:
    from .llm_agents import judge_agent

    return await _run_agent(judge_agent(get_context().settings, name=f"opinion_judge_{uuid.uuid4().hex[:6]}"), state, "assessment", Assessment)


# --- The agents ------------------------------------------------------------------------------------

async def find_stances(ctx: dict[str, Any], camps: dict[str, str], location: Optional[str]) -> dict[str, Any]:
    """The stance agent: {"issue", "ruling": [...], "opposition": [...]}. Raises on errors; the caller carries on without it."""
    ec = get_context()
    plan = await _stance_plan(ctx, camps)
    if plan is None or not plan.issue.strip():
        return {"issue": "", "ruling": [], "opposition": []}
    queries = {"ruling": clean_queries(plan.ruling_queries, ctx["statement"])[:2], "opposition": clean_queries(plan.opposition_queries, ctx["statement"])[:2]}
    issue = _clip(plan.issue, 240)

    async def one(camp: str) -> list[Source]:
        if not queries[camp]:
            return []
        found = await _search(queries[camp], f"Find what {camps[camp]} has said or done on this issue, preferring its own statements and "
                                             f"official documents, then reporting that attributes the position to it. Issue: {issue}", location)
        return [s for s in split_sources(found, ctx, ec.policy)[0] if s.independence != EPISODE]

    groups = dict(zip(CAMPS, await asyncio.gather(*(one(c) for c in CAMPS))))
    chosen = pick_stance_pages(groups)
    out: dict[str, Any] = {"issue": issue, "ruling": [], "opposition": [], "queries": queries["ruling"] + queries["opposition"], "dropped": 0}
    if not chosen:
        return out
    pages = await _fetch(chosen, [PlanPoint(text=issue, kind="other", queries=[], challenge_queries=[])], [])
    findings = await _stance_read(issue, camps, pages) if pages else []
    kept, out["dropped"] = verify_stances(findings, pages)
    out.update(kept)
    return out


async def read_bias(ctx: dict[str, Any], camps: dict[str, str], research: Research, stances: Optional[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """The bias agent: verified signals and which camp's stated position the answer is closest to."""
    speaker, show = profile_text(ctx.get("speaker") or {}, SPEAKER_KEYS), profile_text(ctx.get("creator") or {}, SHOW_KEYS)
    found, stance_lines = findings_text(research), stances_text(camps, stances)
    state = {"ruling": camps["ruling"], "opposition": camps["opposition"], "question": wrap_untrusted("QUESTION", ctx.get("question") or "(not asked directly)"),
             "answer": wrap_untrusted("ANSWER", ctx["statement"]), "speaker": wrap_untrusted("PROFILE", speaker or "no profile found"),
             "show": wrap_untrusted("PROFILE", show or "no profile found"), "findings": wrap_untrusted("FINDINGS", found),
             "stances": wrap_untrusted("STANCES", stance_lines)}
    out = await _bias(state)
    if out is None:
        return [], "unclear"
    corpus = [ctx["statement"], ctx.get("question") or "", speaker, show, found, stance_lines]
    return verify_signals(out.signals, corpus)[0], out.matches


async def judge(ctx: dict[str, Any], camps: dict[str, str], research: Research, stances: Optional[dict[str, Any]],
                signals: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    sp = ctx.get("speaker") or {}
    speaker_line = ", ".join(x for x in (sp.get("name") or sp.get("label"), sp.get("role")) if x) or "unknown"
    numbered = "\n".join(f"{i}. [{s['kind']}] {s['text']} \"{s['quote']}\"" for i, s in enumerate(signals, 1)) or "none"
    state = {"question": wrap_untrusted("QUESTION", ctx.get("question") or "(not asked directly)"), "answer": wrap_untrusted("ANSWER", ctx["statement"]),
             "speaker_line": speaker_line, "findings": wrap_untrusted("FINDINGS", findings_text(research)),
             "stances": wrap_untrusted("STANCES", stances_text(camps, stances)), "signals": wrap_untrusted("SIGNALS", numbered)}
    out = await _judge(state)
    if out is None:
        return None
    has_evidence = bool(stances and (stances.get("ruling") or stances.get("opposition"))) or any(p["findings"] for p in research.points)
    return clean_assessment(out, signals, has_evidence)


async def research_and_assess(ctx: dict[str, Any], route: str, location: Optional[str]) -> Research:
    """Flow: source agent and stance agent in parallel, then the bias agent, then the judge. ResearchUnavailable still means the
    plain search; any failure after the research leaves the research without an assessment."""
    ec = get_context()
    camps = camps_for(ec.policy, location)
    research, stances = await asyncio.gather(research_answer(ctx, location), find_stances(ctx, camps, location), return_exceptions=True)
    if isinstance(stances, BaseException):
        if is_budget_error(stances):
            raise stances
        ec.log("opinion", "stance_failed", "skipped", f"{type(stances).__name__}: {stances}"[:200])
        stances = None
    if isinstance(research, BaseException):
        raise research
    try:
        signals, matches = await read_bias(ctx, camps, research, stances)
        assessment = await judge(ctx, camps, research, stances, signals)
    except Exception as e:
        if is_budget_error(e):
            raise
        ec.log("opinion", "assessment_failed", "skipped", f"{type(e).__name__}: {e}"[:200])
        log.warning("opinion assessment failed: %s: %s", type(e).__name__, e)
        return research
    if assessment is None:
        return research
    research.opinion = {
        "version": 1, "camps": {c: camps[c] for c in CAMPS}, "issue": (stances or {}).get("issue", ""),
        "stances": {c: (stances or {}).get(c, []) for c in CAMPS}, "signals": signals, "matches": matches, "assessment": assessment,
    }
    return research
