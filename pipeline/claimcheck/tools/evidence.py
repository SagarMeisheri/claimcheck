"""One web search for one claim, via Parallel. The verifier workflow runs up to three of these at once.

The model only proposes a query and a scope ("tier1" or "open"); the number of searches, domains, limits and
blocklists are decided in code. Guardrails in here:
- domains come from policy.yaml (tier-1 list per PESTLE area, or open web minus blocklist)
- blocklisted results are dropped even if returned
- fetched text is screened for prompt injection and wrapped as untrusted data
- every call is costed against the episode budget
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..context import get_context
from ..guardrails.injection import screen_text
from ..policy import blocklist, source_tier, tier1_domains_for

MAX_DOC_CHARS = 15000
TOP_EXTRACT = 3


def _client(settings):
    from parallel import Parallel

    return Parallel(api_key=settings.parallel_api_key)


async def run_search(item: dict[str, Any]) -> dict[str, Any]:
    """Searches the web for evidence about one claim and fetches the top sources into ctx.evidence.

    item: {claim_key, claim_index, claim_text, pestle_area, query, scope, purpose}.
    Never raises: a failed search comes back as {"error": ...} so the other searches still count.
    """
    ctx = get_context()
    claim_key, claim_index = item["claim_key"], item.get("claim_index")
    scope, query = item["scope"], item["query"]
    if scope == "tier1":
        source_policy = {"include_domains": tier1_domains_for(item.get("pestle_area", "economic"), ctx.policy)}
    else:
        source_policy = {"exclude_domains": blocklist(ctx.policy)}

    already = ctx.evidence.setdefault(claim_key, {})
    try:
        docs = await asyncio.wait_for(
            _search_extract_live(query, item.get("claim_text", ""), source_policy, set(already)),
            timeout=ctx.settings.tool_timeout_s,
        )
    except Exception as e:  # timeout, API error: record it and let the other searches carry on
        ctx.log("evidence", "search_failed", "skipped", f"{type(e).__name__}: {e}"[:200], claim_index)
        return {"scope": scope, "purpose": item.get("purpose"), "sources_found": 0, "error": type(e).__name__}
    ctx.budget.add(ctx.settings.search_cost_usd + ctx.settings.extract_cost_usd * len(docs))

    found = 0
    for d in docs:
        tier = source_tier(d["url"], ctx.policy)
        if tier == 9:
            ctx.log("evidence", "blocklisted_source", "blocked", d["url"], claim_index)
            continue
        text, hits = screen_text(d.get("text", ""))
        if hits:
            ctx.log("evidence", "prompt_injection_in_source", "flagged", f"{d['url']}: {hits[0]}", claim_index)
        already[d["url"]] = {"title": d.get("title", ""), "text": text[:MAX_DOC_CHARS], "tier": tier,
                             "publish_date": d.get("publish_date")}
        found += 1
    return {"scope": scope, "purpose": item.get("purpose"), "sources_found": found}


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
