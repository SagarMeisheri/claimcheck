"""Run one video from the command line.

  python -m claimcheck.cli https://www.youtube.com/watch?v=VIDEO_ID
  python -m claimcheck.cli --sources CLAIM_ID            # look up sources for one stored claim
  python -m claimcheck.cli --sources-all EPISODE_ID      # look up sources for every statement of a video
  python -m claimcheck.cli --qa EPISODE_ID               # the questions for a finished video's Q&A tab
  python -m claimcheck.cli --relink-channels             # give videos saved without a channel their channel + creator

Needs the keys and Supabase settings from pipeline/.env (see .env.example).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import warnings


def main() -> None:
    ap = argparse.ArgumentParser(description="ClaimCheck: tag the statements in one YouTube video")
    ap.add_argument("url", nargs="?")
    ap.add_argument("--sources", metavar="CLAIM_ID", help="look up sources for one stored claim")
    ap.add_argument("--sources-all", metavar="EPISODE_ID", help="look up sources for every statement of a video")
    ap.add_argument("--qa", metavar="EPISODE_ID", help="write the Q&A questions for a finished video")
    ap.add_argument("--relink-channels", action="store_true",
                    help="give videos saved without a channel their channel (and creator profile, if any)")
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
    if args.sources:
        from .agents.sources import precheck, run_claim_sources

        ok, reason, _ = precheck(asyncio.run(store.get_claim_for_sources(args.sources)), settings)
        if not ok:
            print("Can't look up sources:", reason)
            return
        asyncio.run(store.start_claim_sources(args.sources))
        print(json.dumps(asyncio.run(run_claim_sources(args.sources, settings=settings, store=store)), indent=2))
        return
    if args.qa:
        from .agents.qa import generate_qa

        print(json.dumps(asyncio.run(generate_qa(args.qa, settings=settings, store=store)), indent=2))
        return
    if args.relink_channels:
        from .maintenance import relink_channels

        print(json.dumps(asyncio.run(relink_channels(store, settings)), indent=2))
        return
    if args.sources_all:
        from .agents.sources import run_video_sources

        print(json.dumps(asyncio.run(run_video_sources(args.sources_all, settings=settings, store=store)), indent=2))
        return
    if not args.url:
        ap.error("give a YouTube URL, --sources CLAIM_ID or --sources-all EPISODE_ID")
    result = asyncio.run(run_episode(args.url, settings=settings, store=store))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return
    print(f"\nEpisode {result.get('episode_id')}: {result['status']}")
    if result.get("skip_reason") or result.get("reason"):
        print("Reason:", result.get("skip_reason") or result.get("reason"))
    if result.get("episode_id"):
        rows = (store.db.table("claims").select("id, start_s, claim_text, statement_type, sources_status")
                .eq("episode_id", result["episode_id"]).order("start_s").execute().data)
        for r in rows:
            kind = r["statement_type"].replace("_", " ")
            extra = f" (sources on request: {r['id']})" if r["sources_status"] == "not_requested" else ""
            print(f"  [{r['start_s'] // 60}:{r['start_s'] % 60:02d}] {kind}{extra}: {r['claim_text']}")
    print(f"Statements: {result.get('statement_counts')}  Cost: ${result.get('cost_usd', 0):.4f}")
    print(f"Guardrail events: {len(result.get('guardrail_events', []))}")


if __name__ == "__main__":
    main()
