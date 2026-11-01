"""Gold-set evaluation: rerun on every prompt or model change (week 1-2 gates).

Gold file format (JSONL), one video per line:
  {"url": "https://www.youtube.com/watch?v=...", "side": "supportive|critical|neutral",
   "claims": [{"match": "4 crore houses", "verdict": "supported"}, ...]}

`match` is a case-insensitive substring of the extracted claim text.

Reports: extraction recall, verdict agreement, False<->Supported confusion (must be <= 3%),
skipped claims, and cost per video.

  python -m evals.run_eval evals/gold_set.example.jsonl
"""

from __future__ import annotations

import asyncio
import json
import sys
import warnings
from collections import Counter

warnings.filterwarnings("ignore")
import logging
logging.getLogger("google_adk").setLevel(logging.ERROR)


async def main(path: str) -> None:
    from claimcheck.agents.pipeline import run_episode
    from claimcheck.config import get_settings
    from claimcheck.store import make_store

    settings = get_settings()
    gold = [json.loads(line) for line in open(path) if line.strip()]
    found = agree = total = severe = 0
    costs, confusion = [], Counter()
    for item in gold:
        store = make_store(settings)
        res = await run_episode(item["url"], settings=settings, store=store)
        costs.append(res.get("cost_usd", 0))
        rows = (store.db.table("claims").select("claim_text, not_checked_reason, verdicts(verdict)")
                .eq("episode_id", res.get("episode_id")).execute().data)
        for g in item["claims"]:
            total += 1
            hit = next((r for r in rows if g["match"].lower() in r["claim_text"].lower()), None)
            if hit is None:
                confusion[(g["verdict"], "not_extracted")] += 1
                continue
            found += 1
            got = hit["verdicts"]["verdict"] if hit["verdicts"] else f"not_checked:{hit['not_checked_reason']}"
            confusion[(g["verdict"], got)] += 1
            agree += got == g["verdict"]
            severe += {g["verdict"], got} == {"false", "supported"}
    print(f"Videos: {len(gold)}  Gold claims: {total}")
    print(f"Extraction recall: {found / max(total, 1):.0%}  (gate: >= 80%)")
    print(f"Verdict agreement: {agree / max(total, 1):.0%}  (gate: >= 80%)")
    print(f"False<->Supported confusion: {severe / max(total, 1):.1%}  (gate: <= 3%)")
    print(f"Mean cost per video: ${sum(costs) / max(len(costs), 1):.3f}")
    print("Confusion (expected -> got):")
    for (e, g), n in confusion.most_common():
        print(f"  {e:>12} -> {g}: {n}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "evals/gold_set.example.jsonl"))
