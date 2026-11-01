"""Evidence tool used by the EvidenceAgent, plus escalation via Parallel's Task API.

Guardrails inside the tool (in addition to tool_limits.before_evidence_tool):
- domains come from policy.yaml (tier-1 list per PESTLE area, or open web minus blocklist)
- blocklisted results are dropped even if returned
- fetched text is screened for prompt injection and wrapped as untrusted data
- every call is costed against the episode budget
"""

from __future__ import annotations

import asyncio
from typing import Any

from google.adk.tools.tool_context import ToolContext
from pydantic import BaseModel

from ..context import get_context
from ..guardrails.injection import screen_text
from ..policy import blocklist, source_tier, tier1_domains_for

MAX_DOC_CHARS = 15000
TOP_EXTRACT = 3


class _EscalationSources(BaseModel):
    urls: list[str]


def _client(settings):
    from parallel import Parallel

    return Parallel(api_key=settings.parallel_api_key)


async def search_and_extract(query: str, scope: str, tool_context: ToolContext) -> dict[str, Any]:
    """Searches the web for evidence about the current claim and fetches the top sources.

    Args:
      query: A self-contained search query (entity, metric, period, place).
      scope: "tier1" to search only official sources for this topic first; "open" to search the wider web.

    Returns:
      A short list of sources found (url, title, tier, publish_date, excerpt). Full text is passed to the judge separately.
    """
    ctx = get_context()
    st = tool_context.state
    claim_key = st["claim_key"]
    area = st.get("pestle_area", "economic")
    claim_index = st.get("claim_index")
    if scope == "tier1":
        source_policy = {"include_domains": tier1_domains_for(area, ctx.policy)}
    else:
        source_policy = {"exclude_domains": blocklist(ctx.policy)}

    already = ctx.evidence.setdefault(claim_key, {})
    docs = await asyncio.wait_for(
        _search_extract_live(query, st.get("claim_text", ""), source_policy, set(already)),
        timeout=ctx.settings.tool_timeout_s,
    )
    ctx.budget.add(ctx.settings.search_cost_usd + ctx.settings.extract_cost_usd * len(docs))

    found = []
    for d in docs:
        tier = source_tier(d["url"], ctx.policy)
        if tier == 9:
            ctx.log("evidence", "blocklisted_source", "blocked", d["url"], claim_index)
            continue
        text, hits = screen_text(d.get("text", ""))
        if hits:
            ctx.log("evidence", "prompt_injection_in_source", "flagged", f"{d['url']}: {hits[0]}", claim_index)
        text = text[:MAX_DOC_CHARS]
        already[d["url"]] = {"title": d.get("title", ""), "text": text, "tier": tier, "publish_date": d.get("publish_date")}
        found.append({"url": d["url"], "title": d.get("title", ""), "tier": tier,
                      "publish_date": d.get("publish_date"), "excerpt": text[:800]})
    return {"scope": scope, "sources_found": len(found), "sources": found}


async def _search_extract_live(query: str, objective: str, source_policy: dict, skip: set[str]) -> list[dict[str, Any]]:
    ctx = get_context()
    client = _client(ctx.settings)

    def _run() -> list[dict[str, Any]]:
        res = client.search(
            search_queries=[query],
            objective=f"Find primary-source evidence that confirms or contradicts this claim: {objective}",
            mode="fast",
            advanced_settings={"max_results": 6, "source_policy": source_policy, "location": "in"},
        )
        urls = [r.url for r in res.results if r.url not in skip and source_tier(r.url, ctx.policy) != 9][:TOP_EXTRACT]
        if not urls:
            return []
        ext = client.extract(urls=urls, objective=objective, advanced_settings={"full_content": True})
        out = []
        for r in ext.results:
            text = r.full_content or "\n".join(r.excerpts)
            out.append({"url": r.url, "title": r.title or "", "text": text, "publish_date": r.publish_date})
        return out

    return await asyncio.to_thread(_run)


async def escalate_sources(claim_key: str, claim_text: str) -> int:
    """Asks Parallel's Task API (core) for better primary sources, then extracts them into the claim's evidence.

    Returns the number of new documents added.
    """
    ctx = get_context()
    client = _client(ctx.settings)

    def _run() -> list[dict[str, Any]]:
        run = client.task_run.execute(
            input=("List up to 3 URLs of primary sources (government statistics, official documents, "
                   f"peer-reviewed studies) that directly confirm or contradict this claim: {claim_text}"),
            processor="core",
            output=_EscalationSources,
        )
        urls = [u for u in run.output.parsed.urls if source_tier(u, ctx.policy) != 9][:3]
        if not urls:
            return []
        ext = client.extract(urls=urls, objective=claim_text, advanced_settings={"full_content": True})
        return [{"url": r.url, "title": r.title or "", "text": r.full_content or "\n".join(r.excerpts),
                 "publish_date": r.publish_date} for r in ext.results]

    docs = await asyncio.wait_for(asyncio.to_thread(_run), timeout=600)
    ctx.budget.add(ctx.settings.task_core_cost_usd + ctx.settings.extract_cost_usd * len(docs))
    bucket = ctx.evidence.setdefault(claim_key, {})
    added = 0
    for d in docs:
        text, hits = screen_text(d["text"])
        if hits:
            ctx.log("escalation", "prompt_injection_in_source", "flagged", d["url"])
        if d["url"] not in bucket:
            bucket[d["url"]] = {"title": d["title"], "text": text[:MAX_DOC_CHARS],
                                "tier": source_tier(d["url"], ctx.policy), "publish_date": d["publish_date"]}
            added += 1
    return added
