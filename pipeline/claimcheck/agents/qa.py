"""Q&A view of a video: a model picks the questions a reader would ask and which stored statements answer each one.

It never writes an answer. The page shows the cited statements as they are, with the sources found for them, so what a
reader sees under a question is what the speaker said (as extracted) and what the web pages say, not new model text.
Code checks every item before it is saved: the statements exist, the question uses no number that the cited statements
lack, it doesn't ask for a verdict, and it isn't a repeat.

Saved as episodes.qa = [{"q": question, "claim_ids": [claims.id, ...]}], in the order the answers come in the video.
  python -m claimcheck.cli --qa EPISODE_ID
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from google.adk.runners import InMemoryRunner
from google.genai import types

from ..config import Settings
from ..context import get_context, is_budget_error, set_context
from ..guardrails.injection import screen_text, wrap_untrusted
from ..schemas import QaItemOut, QaOut
from .sources import _JUDGING, _context, lock_for

log = logging.getLogger("claimcheck")
APP = "claimcheck_qa"
MAX_QUESTIONS = 12
MAX_QUESTION_CHARS = 160
MIN_QUESTION_CHARS = 15
MAX_STATEMENTS_PER_QUESTION = 3
QA_COST_ESTIMATE_USD = 0.05  # one call over the whole statement list; the most it should cost
_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


def eligible(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Statements a question may be built on: not questions, not redacted, in the order said."""
    keep = [r for r in rows if r.get("statement_type") != "question" and r.get("policy_tier") != "never"
            and r.get("not_checked_reason") != "outside_policy" and (r.get("claim_text") or "").strip()]
    return sorted(keep, key=lambda r: r.get("start_s") or 0)


def numbered_text(rows: list[dict[str, Any]]) -> str:
    """'[3] 47m · Sohini Rajola · factual_claim · web pages found: text' per statement; the number is what the model cites."""
    lines = []
    for i, r in enumerate(rows, 1):
        who = (r.get("speaker") or "").strip() or "Speaker"
        text, _ = screen_text(r["claim_text"])
        pages = " · web pages found" if r.get("sources_status") == "done" else ""
        lines.append(f"[{i}] {int(r.get('start_s') or 0) // 60}m · {who} · {r.get('statement_type', 'other')}{pages}: {text}")
    return wrap_untrusted("STATEMENTS", "\n".join(lines))


def _numbers(text: str) -> set[str]:
    return {n.rstrip(".,").replace(",", "") for n in _NUMBER.findall(text or "")}


def validate_items(items: list[QaItemOut], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The items worth saving, as {"q", "claim_ids"}. `rows` are the numbered statements, 1-based in the order given."""
    out: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    for it in items:
        q = re.sub(r"\s+", " ", it.question or "").strip()
        picked: list[int] = []
        for n in it.statements or []:
            if isinstance(n, int) and 1 <= n <= len(rows) and n not in picked:
                picked.append(n)
        picked = picked[:MAX_STATEMENTS_PER_QUESTION]
        if not picked or not (MIN_QUESTION_CHARS <= len(q) <= MAX_QUESTION_CHARS) or not q.endswith("?"):
            continue
        if _JUDGING.search(q):  # asks for a verdict
            continue
        cited = " ".join(rows[n - 1]["claim_text"] for n in picked)
        if not _numbers(q) <= _numbers(cited):  # a figure the statements don't contain
            continue
        key = re.sub(r"[^\w]+", " ", q.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        picked.sort(key=lambda n: rows[n - 1].get("start_s") or 0)
        out.append((rows[picked[0] - 1].get("start_s") or 0, {"q": q, "claim_ids": [rows[n - 1]["id"] for n in picked]}))
    out.sort(key=lambda t: t[0])
    return [item for _, item in out[:MAX_QUESTIONS]]


async def _ask(rows: list[dict[str, Any]]) -> Optional[QaOut]:
    from .llm_agents import qa_agent

    ec = get_context()
    runner = InMemoryRunner(agent=qa_agent(ec.settings, name=f"qa_writer_{uuid.uuid4().hex[:6]}"), app_name=APP,
                            plugins=ec.plugins_factory())
    session = await runner.session_service.create_session(app_name=APP, user_id="qa", state={"statements": numbered_text(rows)})
    msg = types.Content(role="user", parts=[types.Part(text="Write the questions.")])
    async for _ in runner.run_async(user_id="qa", session_id=session.id, new_message=msg):
        pass
    done = await runner.session_service.get_session(app_name=APP, user_id="qa", session_id=session.id)
    raw = done.state.get("qa")
    return QaOut.model_validate(raw) if raw else None


async def generate_qa(episode_id: str, *, settings: Settings, store: Any) -> dict[str, Any]:
    """Writes episodes.qa for a finished video. Never raises; the result says what happened."""
    async with lock_for(episode_id):
        ep = await store.get_episode(episode_id)
        if not ep or ep.get("status") not in ("done", "in_review"):
            return {"status": "skipped", "reason": "The video hasn't finished being analysed."}
        spent = float(ep.get("cost_usd") or 0)
        if spent + QA_COST_ESTIMATE_USD > settings.max_cost_usd_per_episode:
            return {"status": "skipped", "reason": "This video has used its budget."}
        all_rows = await store.list_claims_for_qa(episode_id)
        if any(r.get("question") for r in all_rows):
            return {"status": "skipped", "reason": "This video's answers already come with their questions."}
        rows = eligible(all_rows)
        if len(rows) < 5:
            return {"status": "skipped", "reason": "Too few statements for a Q&A page."}
        ec = _context(episode_id, ep, settings, store)
        start = ec.budget.spent_usd
        token = set_context(ec)
        result: dict[str, Any]
        try:
            out = await _ask(rows)
            items = validate_items(out.items, rows) if out else []
            if items:
                await store.update_episode(episode_id, {"qa": items, "qa_generated_at": datetime.now(timezone.utc).isoformat()})
                result = {"status": "done", "questions": len(items), "proposed": len(out.items) if out else 0}
            else:
                result = {"status": "failed", "reason": "No usable questions came back."}
        except Exception as e:
            reason = "budget" if is_budget_error(e) else f"{type(e).__name__}: {e}"
            log.warning("Q&A for episode %s failed: %s", episode_id, reason)
            result = {"status": "failed", "reason": reason[:200]}
        finally:
            cost = round(ec.budget.spent_usd - start, 6)
            try:
                await store.add_episode_cost(episode_id, cost, ec.budget.tokens_in, ec.budget.tokens_out)
                await store.save_guardrail_events(episode_id, ec.events)
            except Exception:
                log.exception("could not record Q&A cost for %s", episode_id)
            try:
                token.var.reset(token)
            except ValueError:
                pass
        result["cost_usd"] = round(cost, 4)
        return result
