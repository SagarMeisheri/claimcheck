# ClaimCheck MVP

Turns a YouTube video into a scorecard of its factual claims: each claim gets a verdict, an exact quote from an official or reliable source, and a link to the moment it was said. Built for Indian political, finance and health videos.

```
pipeline/   Python service: Google ADK agents + guardrails (Cloud Run)
web/        Next.js 16 app: video feed, watch-and-check screen, channels, balance, review queue, share cards (Vercel)
supabase/   Postgres schema with pgvector cache and row-level security
```

## Run it locally

Needs Docker, the Supabase CLI, Python 3.11+, Node 20+. There is no demo or fake data: the app starts empty and shows only videos you submit.

```bash
supabase start && supabase db reset        # local Postgres with migrations 0001-0004 (ports 55321-55329)

cd pipeline
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                       # add GOOGLE_API_KEY, PARALLEL_API_KEY, YOUTUBE_API_KEY, Supabase keys
pytest                                     # guardrail and policy tests (no keys needed)
python -m claimcheck.cli "https://www.youtube.com/watch?v=VIDEO_ID"
uvicorn claimcheck.server:app --port 8080  # the service the web app calls

cd ../web
cp .env.example .env.local                 # Supabase URL/keys from `supabase status`
npm install && npm run dev                 # http://localhost:3000
```

The YouTube Data API is called once per submitted video (one quota unit, in `pipeline/claimcheck/tools/youtube.py`). Nothing polls it in the background locally; the channel RSS cron only runs on Vercel, and `scripts/seed_channels.py` only when you run it.

## The web app

| Route | Screen |
| --- | --- |
| `/` | Home: each video is a compact header (thumbnail, title, channel, guest), a verdict strip, "X of Y supported, N flagged", and a horizontal carousel of claim cards (strongest supported claim first, then flagged by severity, ending in "See all N claims"). Each card opens that claim on the scorecard or plays 20 s of it. Tabs: Latest, Topics (claims across videos grouped by subject), Following; PESTLE and track filters; search across titles, channels, guests and claim text |
| `/v/VIDEO_ID` | Scorecard, read first: the player is a thumbnail until tapped (no YouTube load), the summary, then Flagged / All / Topics claim cards. Each card expands in place (sources, reasoning, share, feedback) and has "Watch 20 s", which plays the claim with 3 s of lead-in and then offers Keep watching or Next claim. "Play flagged claims in order" steps through them by itself. The claim track sits under the player; on phones the player and track pin to the top while you read. J/K move between claims. Not checked claims and the method are folded at the end |
| `/v/VIDEO_ID#claim-ID` | Same, with that claim open and the video cued 5 s before it. `?moment=ID` plays that claim's 20 s, `?view=all\|flagged\|topics` picks the tab, `?t=640` cues a time, `?play=1` plays |
| `/c/CHANNEL_ID` | Channel page with its checked videos and Follow (stored in the browser) |
| `/submit`, `/balance`, `/method`, `/review` | Check a video (with link preview), balance, method, reviewer queue |

Nothing is drawn over YouTube thumbnails or the player, and the player is never shrunk below 200x200, per YouTube's API policies. UI tests: build, start on port 3100, then `node tests/ui.test.js` (uses a stand-in for the YouTube player script).

## How a video is checked

```
EpisodePipeline (ADK SequentialAgent)
  IngestGate        code   public, 5+ min, not live; metadata treated as untrusted
  TriageAgent       LLM    worthiness, PESTLE mix, share of never-check content
  TriageGate        code   skip if worthiness < 0.5 or > 30% never-check
  ExtractorAgent    LLM    Gemini Flash, YouTube URL with agentic video processing
  ClaimFilter       code   60-claim cap, content policy re-applied in code
  PrioritiserAgent  LLM    check-worthiness score per claim
  Selector          code   top 25
  ClaimFanOut       code   one isolated ADK session per claim, 10 at a time
    ClaimVerifier: cache check -> Normalizer -> JudgeLoop(Evidence -> Judge -> ConfidenceGate) x2
    then: Task API escalation if unsure, second judge for any False, verdict checks, review flag
  Publisher         code   the only writer
```

Guardrails live in `pipeline/claimcheck/guardrails/` and `policy.yaml`:

| Where | Rule |
| --- | --- |
| Every model call | Per-episode cost cap ($3) via an ADK plugin; Model Armor plugin when templates are configured |
| Evidence tool | Model picks only query and scope; domains come from policy (tier-1 list per PESTLE area, blocklist always), 4 searches per claim, 60 s timeout, injection lines stripped from pages |
| Verdicts | Quote must appear in the fetched text; numbers must match (Indian units understood); stricter-tier claims need a tier-1 source; False needs a strong source, confidence >= 0.8 and agreement from a second judge; Disputed needs two sources; reasoning rewritten if it accuses anyone of lying |
| Publishing | Every False, and political Misleading/Disputed, waits for human review; pending verdicts are hidden by RLS and excluded from tallies; never-check claims are stored redacted |

All of these are covered by tests in `pipeline/tests/`.

## Going live

1. **Supabase**: create a project, run `supabase/migrations/0001_init.sql`, `0002_review.sql`, then `0003_ui.sql` (SQL editor or `supabase db push`). Seed channels: `python pipeline/scripts/seed_channels.py` (needs `YOUTUBE_API_KEY`; it prints any handles it couldn't resolve).
2. **Pipeline (Cloud Run)**: `cd pipeline && gcloud run deploy claimcheck-pipeline --source . --set-env-vars ...` with:
   `GOOGLE_API_KEY`, `PARALLEL_API_KEY`, `YOUTUBE_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `PIPELINE_SHARED_SECRET`, and optionally `MODEL_ARMOR_PROMPT_TEMPLATE` / `MODEL_ARMOR_TOOL_TEMPLATE`. Set request timeout to 60 min and CPU always allocated (runs continue after the HTTP response).
3. **Web (Vercel)**: import `web/`, set the variables in `web/.env.example`. The cron in `vercel.json` polls channel RSS every 10 minutes (needs Vercel Pro; Hobby allows daily).
4. **Gold set**: label 20 episodes (10 political, balanced by side) in `pipeline/evals/gold_set.example.jsonl` format and run `python -m evals.run_eval your_gold.jsonl`. Gates: recall >= 80%, agreement >= 80%, False/Supported confusion <= 3%.

Model names and limits are environment variables (`CLAIMCHECK_FAST_MODEL`, `CLAIMCHECK_JUDGE_MODEL`, `CLAIMCHECK_VIDEO_PROCESSING=static` for the fallback, etc.); see `pipeline/claimcheck/config.py`.

## What has and hasn't been verified

Verified: guardrail and policy tests, the SQL schema and RLS (local Supabase, migrations 0001-0004), and the web build and empty-state pages. The full pipeline has not been run against live services yet (see below); the scripted-model pipeline tests and the browser UI tests were removed along with the fake and demo data.

Not yet run against live services: Gemini (including agentic video on a real YouTube URL), Parallel Search/Extract/Task, YouTube Data API, the real YouTube embedded player and thumbnails, Supabase, Model Armor. Expect a short shakedown on first live run. In particular:
- Gemini 4 Argon pricing is an assumption in `config.py` ($2.50/$15 per M tokens).
- Agentic video uses `types.Part(media_processing=AGENTIC)` from google-genai 2.34; confirm your model accepts it, or set `CLAIMCHECK_VIDEO_PROCESSING=static`.
- `SequentialAgent`/`LoopAgent` emit deprecation warnings in ADK 2.13 in favour of the new `Workflow` graph API; they work today, and migrating is a contained change in `agents/pipeline.py` and `agents/verifier.py`.
- The Supabase Python client is synchronous; fine at MVP volume, swap for the async client if throughput matters.

Before launch: have a lawyer review the content policy, corrections process and election-period obligations.
