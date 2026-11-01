"""Run one episode from the command line.

  python -m claimcheck.cli https://www.youtube.com/watch?v=VIDEO_ID

Needs the keys and Supabase settings from pipeline/.env (see .env.example).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import warnings


def main() -> None:
    ap = argparse.ArgumentParser(description="ClaimCheck: verify the claims in one YouTube video")
    ap.add_argument("url")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args()
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("google_adk").setLevel(logging.ERROR)

    from .agents.pipeline import run_episode
    from .config import get_settings
    from .store import make_store

    settings = get_settings()
    store = make_store(settings)
    result = asyncio.run(run_episode(args.url, settings=settings, store=store))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return
    print(f"\nEpisode {result.get('episode_id')}: {result['status']}")
    if result.get("skip_reason") or result.get("reason"):
        print("Reason:", result.get("skip_reason") or result.get("reason"))
    if result.get("episode_id"):
        rows = (store.db.table("claims").select("start_s, claim_text, not_checked_reason, verdicts(verdict, review_status)")
                .eq("episode_id", result["episode_id"]).order("start_s").execute().data)
        for r in rows:
            v = r.get("verdicts")
            label = v["verdict"].upper() if v else f"not checked ({r['not_checked_reason']})"
            review = " [awaiting review]" if v and v["review_status"] == "pending" else ""
            print(f"  [{r['start_s'] // 60}:{r['start_s'] % 60:02d}] {label}{review}: {r['claim_text']}")
    print(f"Tally: {result.get('tally')}  Not checked: {result.get('not_checked')}  "
          f"Pending review: {result.get('pending_review')}  Cost: ${result.get('cost_usd', 0):.4f}")
    print(f"Guardrail events: {len(result.get('guardrail_events', []))}")


if __name__ == "__main__":
    main()
