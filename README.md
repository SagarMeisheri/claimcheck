# ClaimCheck MVP

Turns a YouTube video (especially long podcasts, panels and interviews) into a tagged list of its statements: each one is marked as a claim, opinion, forecast, hearsay, analogy or loaded language, with a link to the moment it was said. Nothing is verified automatically; viewers press **Verify** on the claims they want checked. A verdict comes with an exact quote from an official or reliable source and is saved for everyone. Built for Indian political, finance and health videos.

```
pipeline/   Python service: Google ADK agents + guardrails (Cloud Run)
web/        Next.js 16 app: video feed, watch-and-check screen, channels, balance, review queue, share cards (Vercel)
supabase/   Postgres schema with pgvector cache and row-level security
```

## Run it locally

Needs Docker, the Supabase CLI, Python 3.11+, Node 20+. There is no demo or fake data: the app starts empty and shows only videos you submit.

```bash
supabase start && supabase db reset        # local Postgres with migrations 0001-0006 (ports 55321-55329)

cd pipeline
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                       # add GOOGLE_API_KEY, PARALLEL_API_KEY, YOUTUBE_API_KEY, Supabase keys
pytest                                     # guardrail, policy, tagging and on-demand tests (no keys needed)
python -m claimcheck.cli "https://www.youtube.com/watch?v=VIDEO_ID"
python -m claimcheck.cli --verify-claim CLAIM_ID   # verify one stored claim, as the Verify button does
uvicorn claimcheck.server:app --port 8080  # the service the web app calls

cd ../web
cp .env.example .env.local                 # Supabase URL/keys from `supabase status`
npm install && npm run dev                 # http://localhost:3000
```

The YouTube Data API is called once per submitted video (one quota unit, in `pipeline/claimcheck/tools/youtube.py`). Nothing polls it in the background locally; the channel RSS cron only runs on Vercel, and `scripts/seed_channels.py` only when you run it.

## The web app

| Route | Screen |
| --- | --- |
| `/` | Home: each video is a compact header (thumbnail, title, channel, guest), a verdict strip, "X of Y verified claims supported, N flagged", and a horizontal carousel. The first card is the video's breakdown (statements by type, how many verified, how many with a reviewer) and links to the video page; the rest are verified claims only (strongest supported claim first, then flagged by severity). Each claim card opens that claim on the video page or plays 20 s of it. Tabs: Latest, Topics (verified claims across videos grouped by subject), Following; PESTLE and track filters; search across titles, channels, guests and verified claim text |
| `/v/VIDEO_ID` | Video page: the player is a thumbnail until tapped (no YouTube load), a breakdown of the statements by type, then every statement as a colour-coded card with filter chips (All, Claim, Opinion, Forecast, Hearsay, plus Analogy / Loaded language when present, and Verified). Unverified claims have a **Verify** button that shows Queued / Verifying / With a reviewer while it runs. Verified claims expand in place (sources, reasoning, share, feedback). Every card has "Watch 20 s", which plays the statement with 3 s of lead-in and then offers Keep watching or Next claim. "Play verified claims in order" steps through them by itself. The track under the player has one tick per statement (verdict colour if verified, type colour otherwise); on phones the player and track pin to the top while you read. J/K move between verified claims |
| `/v/VIDEO_ID#claim-ID` | Same, with that claim open and the video cued 5 s before it. `?moment=ID` plays that claim's 20 s, `?view=all\|verified\|factual_claim\|opinion\|forecast\|hearsay\|...` picks the filter (old `flagged`/`checked` links open Verified), `?t=640` cues a time, `?play=1` plays |
| `/c/CHANNEL_ID` | Channel page with its checked videos and Follow (stored in the browser) |
| `/submit`, `/balance`, `/method`, `/review` | Check a video (with link preview), balance, method, reviewer queue |

Nothing is drawn over YouTube thumbnails or the player, and the player is never shrunk below 200x200, per YouTube's API policies. UI tests: build, start on port 3100, then `node tests/ui.test.js` (uses a stand-in for the YouTube player script).

## How a video is checked

A video is analysed in two steps: a first pass that extracts and tags every statement (nothing is verified), then on-demand verification of any claim a viewer picks.

```
EpisodePipeline (ADK SequentialAgent)                       POST /episodes
  IngestGate        code   public, 5+ min, not live; metadata treated as untrusted
  TriageAgent       LLM    worthiness (substantive public-interest content), PESTLE mix, never-check share
  TriageGate        code   skip if worthiness < 0.5 or > 30% never-check
  ExtractorAgent    LLM    Gemini Flash, YouTube URL with agentic video processing; every statement with
                           timestamp and type: factual_claim, opinion, forecast, analogy, loaded_language,
                           hearsay, other
  ClaimFilter       code   150-statement cap; content policy re-applied in code (never-check topics are
                           redacted for every type); only claims are verifiable
    (nothing is verified in this run; a viewer presses Verify, see below)
  Publisher         code   the only writer; also stores statement counts by type

On-demand (agents/on_demand.py)                             POST /claims/{id}/verify
  web app           rate limits (10 per person per day, 120 per hour site-wide), marks the claim queued
  precheck          code   claim, not redacted, not already verified, video under its cost cap
  ClaimVerifier     one video at a time so the cap holds. Cache check (code), then an ADK Workflow:
                    plan (LLM: official / corroborating / counter-evidence searches) -> clamp (code: at most
                    3, never more) -> search (parallel_worker: 3 Parallel search+extract at once, no retries)
                    -> judge (LLM: TRUE / FALSE / UNVERIFIABLE + explanation, correction, cited quotes).
                    Then in code: quote, number and source-tier checks, 0-100 score, review flag
  save              verdict on the claim row (shared by everyone), cost added to the video, tally
                    recomputed; a False (or political Misleading/Disputed) waits for review
```

Each claim row has a `verification_status`: `not_eligible` (not a claim, or redacted), `not_requested`, `queued`, `verifying`, `verified`, `awaiting_review` or `failed` (can be retried). A claim stuck in `queued`/`verifying` for 30 minutes can be requested again, and a pipeline restart marks interrupted ones `failed`.

Guardrails live in `pipeline/claimcheck/guardrails/` and `policy.yaml`:

| Where | Rule |
| --- | --- |
| Every model call | Per-episode cost cap ($3) via an ADK plugin; Model Armor plugin when templates are configured. The cap covers the first pass plus every on-demand verification of that video |
| Verify button | Claims only; 10 requests per person per day (salted IP hash) and 120 per hour site-wide (`VERIFY_PER_PERSON_PER_DAY`, `VERIFY_SITE_PER_HOUR`); a claim is verified once and the verdict reused for everyone |
| Evidence tool | Model picks only query and scope; domains come from policy (tier-1 list per PESTLE area, blocklist always), 4 searches per claim, 60 s timeout, injection lines stripped from pages |
| Verdicts | Quote must appear in the fetched text; numbers must match (Indian units understood); stricter-tier claims need a tier-1 source; False needs a strong source and confidence >= 0.8, otherwise it becomes Unverifiable; a 0-100 truthfulness score is computed in code (none for Unverifiable); reasoning rewritten if it accuses anyone of lying |
| Publishing | Every False, and political Misleading/Disputed, waits for human review, including on-demand ones; pending verdicts are hidden by RLS and excluded from tallies (the claim shows "With a reviewer"); never-check statements are stored redacted |

All of these are covered by tests in `pipeline/tests/`.

## Going live

1. **Supabase**: create a project and run every migration in order (SQL editor, or `supabase db push` which applies them all):
   `0001_init.sql`, `0002_review.sql`, `0003_ui.sql`, `0004_grants.sql` (table privileges; without it the site can't read anything on newer Supabase projects), `0005_progress.sql` (progress bar column) and `0006_statements.sql` (statement types, verification status, statement counts, verify-request log; it backfills existing claims). An existing database only needs the ones it's missing, in order. Deploy order for this change: run `0006` first, then the pipeline, then the web app. Seed channels: `python pipeline/scripts/seed_channels.py` (needs `YOUTUBE_API_KEY`; it prints any handles it couldn't resolve).
2. **Pipeline (Cloud Run)**: `cd pipeline && gcloud run deploy claimcheck-pipeline --source . --set-env-vars ...` with:
   `GOOGLE_API_KEY`, `PARALLEL_API_KEY`, `YOUTUBE_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `PIPELINE_SHARED_SECRET`, and optionally `MODEL_ARMOR_PROMPT_TEMPLATE` / `MODEL_ARMOR_TOOL_TEMPLATE`. Set request timeout to 60 min and CPU always allocated (runs continue after the HTTP response). Keep `--max-instances=1`: runs, and the per-video lock that keeps on-demand verifications under the cost cap, live in memory.
3. **Web (Vercel)**: import `web/`, set the variables in `web/.env.example` (optionally `VERIFY_PER_PERSON_PER_DAY` and `VERIFY_SITE_PER_HOUR` for the Verify button). The cron in `vercel.json` polls channel RSS every 10 minutes (needs Vercel Pro; Hobby allows daily).
4. **Gold set**: label 20 episodes (10 political, balanced by side) in `pipeline/evals/gold_set.example.jsonl` format and run `python -m evals.run_eval your_gold.jsonl`. Gates: recall >= 80%, agreement >= 80%, False/Supported confusion <= 3%.

Model names and limits are environment variables (`CLAIMCHECK_FAST_MODEL`, `CLAIMCHECK_JUDGE_MODEL`, `CLAIMCHECK_VIDEO_PROCESSING=static` for the fallback, etc.); see `pipeline/claimcheck/config.py`.

## What has and hasn't been verified

Verified: guardrail, policy, tagging and on-demand tests, the SQL schema and RLS (local Supabase, migrations 0001-0004; 0006 in PGlite with `supabase/test_statements_migration.mjs`), and the web build and empty-state pages. The full pipeline has not been run against live services yet (see below); the scripted-model pipeline tests and the browser UI tests were removed along with the fake and demo data.

Not yet run against live services: Gemini (including agentic video on a real YouTube URL), Parallel Search/Extract/Task, YouTube Data API, the real YouTube embedded player and thumbnails, Supabase, Model Armor. Expect a short shakedown on first live run. In particular:
- Gemini 4 Argon pricing is an assumption in `config.py` ($2.50/$15 per M tokens).
- Agentic video uses `types.Part(media_processing=AGENTIC)` from google-genai 2.34; confirm your model accepts it, or set `CLAIMCHECK_VIDEO_PROCESSING=static`.
- The claim verifier uses the ADK `Workflow` graph API. The first-pass pipeline (`agents/pipeline.py`) still uses `SequentialAgent`, which emits a deprecation warning in ADK 2.13.
- The Supabase Python client is synchronous; fine at MVP volume, swap for the async client if throughput matters.

Before launch: have a lawyer review the content policy, corrections process and election-period obligations.
