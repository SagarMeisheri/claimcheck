"""Gold-set evaluation: rerun on every prompt or model change.

Gold file format (JSONL), one video per line:
  {"url": "https://www.youtube.com/watch?v=...",
   "statements": [{"match": "4 crore houses", "type": "factual_claim", "source_domain": "pib.gov.in"}, ...]}

`match` is a case-insensitive substring of the extracted statement text. `type` is the expected tag
(factual_claim, opinion, forecast, other). `source_domain` is optional: for factual claims, a site that
"Check sources" should find (the lookup is run for those claims, so it costs searches).

Reports: extraction recall, tag agreement, source recall (when source_domain is given) and cost per video.
Gates: recall >= 80%, tag agreement >= 80%.

  python -m evals.run_eval evals/gold_set.example.jsonl
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import warnings
from collections import Counter

warnings.filterwarnings("ignore")
logging.getLogger("google_adk").setLevel(logging.ERROR)


async def main(path: str) -> None:
    from claimcheck.agents.pipeline import run_episode
    from claimcheck.agents.sources import run_claim_sources
    from claimcheck.config import get_settings
    from claimcheck.policy import domain_of
    from claimcheck.store import make_store

    settings = get_settings()
    store = make_store(settings)
    gold = [json.loads(line) for line in open(path) if line.strip()]
    found = agree = total = src_total = src_found = 0
    costs: list[float] = []
    confusion: Counter = Counter()
    for item in gold:
        res = await run_episode(item["url"], settings=settings, store=store)
        rows = (store.db.table("claims").select("id, claim_text, statement_type, sources_status")
                .eq("episode_id", res.get("episode_id")).execute().data)
        for g in item["statements"]:
            total += 1
            hit = next((r for r in rows if g["match"].lower() in r["claim_text"].lower()), None)
            if hit is None:
                confusion[(g["type"], "not_extracted")] += 1
                continue
            found += 1
            confusion[(g["type"], hit["statement_type"])] += 1
            agree += hit["statement_type"] == g["type"]
            if g.get("source_domain") and hit["statement_type"] == "factual_claim":
                src_total += 1
                if hit["sources_status"] != "done" and await store.start_claim_sources(hit["id"]):
                    await run_claim_sources(hit["id"], settings=settings, store=store)
                urls = [s["url"] for s in store.db.table("claim_sources").select("url").eq("claim_id", hit["id"]).execute().data]
                src_found += any(domain_of(u).endswith(g["source_domain"]) for u in urls)
        ep = store.db.table("episodes").select("cost_usd").eq("id", res.get("episode_id")).execute().data
        costs.append(float((ep[0] if ep else {}).get("cost_usd") or 0))
    print(f"Videos: {len(gold)}  Gold statements: {total}")
    print(f"Extraction recall: {found / max(total, 1):.0%}  (gate: >= 80%)")
    print(f"Tag agreement: {agree / max(total, 1):.0%}  (gate: >= 80%)")
    if src_total:
        print(f"Source recall: {src_found / src_total:.0%} of {src_total} claims found the expected site")
    print(f"Mean cost per video: ${sum(costs) / max(len(costs), 1):.3f}")
    print("Confusion (expected -> got):")
    for (e, g), n in confusion.most_common():
        print(f"  {e:>14} -> {g}: {n}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "evals/gold_set.example.jsonl"))
