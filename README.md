# ClaimCheck

Paste a YouTube link (any public, finished video) and ClaimCheck breaks it into what was said: an AI summary and
every statement with its timestamp, tagged as a **claim, opinion, forecast or other**, filterable by type and
subject, playable 20 s at a time. For a claim, a viewer can press **Check sources**: one web search on the claim's
wording, showing the top 5 results as the search returned them (title, link, site, date and the relevant passage),
with a 1-2 sentence AI summary of those excerpts ("Sources summary") and a source match (High / Medium / Low): how
directly the excerpts address the claim's specific point, which is relevance, not agreement.

**ClaimCheck is not a fact-checker.** Nothing is judged true or false, there are no scores, and sources are search
results shown for context only; their summary describes what the pages say and never whether a claim is right. Earlier versions published verdicts; that was removed (see `REPORT-adoption-and-legal.md` for why), and
old verdict data is kept in the database but hidden from the public (migration 0012).

```
pipeline/   Python service: Google ADK agents + guardrails (Cloud Run)
web/        Next.js 16 app: feed, video page, channels, reviewer page (Vercel)
supabase/   Postgres schema, row-level security and column grants
```

## Run it locally

Needs Docker, the Supabase CLI, Python 3.11+, Node 20+. There is no demo data: the app shows only videos you submit.

```bash
supabase start && supabase db reset        # local Postgres with migrations 0001-0015 (ports 55321-55329)

cd pipeline
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                       # GOOGLE_API_KEY, PARALLEL_API_KEY, YOUTUBE_API_KEY, Supabase keys
pytest                                     # all tests run offline, no keys needed
python -m claimcheck.cli "https://www.youtube.com/watch?v=VIDEO_ID"
python -m claimcheck.cli --sources CLAIM_ID        # look up sources for one claim, as the button does
python -m claimcheck.cli --sources-all EPISODE_ID  # "Check sources for all claims"
python -m claimcheck.cli --summarize-missing       # summary + match for claims looked up before them
uvicorn claimcheck.server:app --port 8080  # the service the web app calls

cd ../web
cp .env.example .env.local                 # Supabase URL/keys from `supabase status`
npm install && npm run dev                 # http://localhost:3000
```

## The web app

| Route | Screen |
| --- | --- |
| `/` | Feed of analysed videos: thumbnail, AI summary, breakdown by type, "Check sources for all claims", and a paged carousel of statements (tabs by type, subject chips). Each statement plays in place from its timestamp. Tabs: Latest, Topics (claims across videos by subject), Following (stored in the browser). Search and PESTLE filters |
| `/v/VIDEO_ID` | Video page: player (loads only on tap, YouTube's own defaults), a track with one tick per statement, AI summary, filter chips (All, Claim, Opinion, Forecast, Other, With sources) and subject chips. Each statement card shows the AI's wording, the speaker "(identified by AI)", "What was said" (AI transcript, labelled), Watch 20 s, Share, Report a problem, and for claims Check sources / the sources found. "Play in order", J/K |
| `/v/VIDEO_ID#claim-ID` | Same, cued to that statement. `?moment=ID` plays its 20 s, `?view=all\|with_sources\|factual_claim\|opinion\|forecast\|other`, `?t=640`, `?play=1` |
| `/c/CHANNEL_ID` | A channel's analysed videos and Follow |
| `/submit` | Analyse a video (with link preview) |
| `/method`, `/privacy` | How it works (limits of AI output, what isn't shown, reporting); privacy and YouTube terms |
| `/review` | Reviewer (HTTP basic auth): open reports (hide statement, mark fixed, nothing wrong) and the videos list (stop, delete) |

Nothing is drawn over YouTube thumbnails or the player, the player's speed and captions are YouTube's defaults, and
it is never shrunk below 200x200, per YouTube's API policies.

## How a video is analysed

```
EpisodePipeline (ADK SequentialAgent)                       POST /episodes
  IngestGate      code   public and finished (not live); title/description treated as untrusted
  ExtractorAgent  LLM    Gemini 3.8 Flash reads the YouTube URL (agentic video processing): every statement with
                         timestamp, speaker (a name only if said or shown), tag (claim / opinion / forecast / other),
                         1-2 subject tags, plus a neutral 2-3 sentence summary. Statements stream to the database as
                         they are written
  ClaimFilter     code   150-statement cap; never-show topics redacted in code whatever the model said
  Publisher       code   the only writer; statement counts, summary, cost

Sources (agents/sources.py, tools/evidence.py): nothing filtered after the search
  One claim                                                   POST /claims/{id}/sources
    web app       rate limits (10 per person per day, 120 per hour site-wide), marks the claim queued
    precheck      a claim, not redacted, no sources yet, video under its cost cap; one lookup per video at a time
    search        one Parallel search ("fast") on the claim's own words; social media and video sites excluded in
                  the request. Top 5 results kept in Parallel's order: title, link, date, site label (official /
                  news or research / none) and the passage of the page text that shares the most words and numbers
                  with the claim. ~$0.005, about a second
    summarize     ADK LlmAgent on Gemini 3.5 Flash-Lite: 1-2 plain sentences (<= 45 words) summarising the excerpts
                  shown under the sources, and only those (so a reader can check it), with their figures and dates.
                  The same call rates the source match (high / medium / low): how directly the excerpts address
                  the claim's specific point. Relevance only, never agreement: a different figure for the same thing
                  is "high". Describes, never judges: a summary with judging words (confirms, contradicts, true,
                  false, ...) is dropped in code. If it fails, the sources are saved without either. ~$0.0005
    save          on the claim for everyone (claim_sources rows + claims.sources_summary), or "no sources found"
  Every claim of a video                                      POST /episodes/{id}/sources-all
    the same search and summary for each claim without sources, 5 at a time, each saved as it lands. Up to 25 searches per
    press (earliest claims first; press again for more), never beyond the video's budget; claims with the same
    wording share one search

  Why not one search for many claims: Parallel takes several queries per request but returns one merged list with
  no link from a result back to its query, so results can't be attributed to a claim without a model guessing.
```

Each claim has a `sources_status`: `not_eligible` (not a claim, or redacted), `not_requested`, `queued`, `searching`,
`done` (sources saved, possibly none) or `failed` (can be retried). A pipeline restart marks interrupted ones `failed`.

## Guardrails (`pipeline/claimcheck/guardrails/`, `policy.yaml`)

| Where | Rule |
| --- | --- |
| Every model call | Per-video cost cap ($3) via an ADK plugin, covering the first pass and every source search ($0.005 each); counts prompt, output, thinking **and tool-use** tokens (agentic video bills frames and transcript as tool use). Prices in `config.py` use the published 2027 Flash price so the cap never undercounts. Model Armor plugin when templates are configured |
| Prompts | Describe, never evaluate; no prompt asks whether a claim is true or for a view of a speaker. All video text and fetched pages are wrapped as untrusted data; instruction-like lines in pages are removed |
| Buttons | Claims only; 10 "Check sources" per person per day and 120 per hour site-wide, 3 "Check sources for all" per person per day and 20 per hour (`SOURCES_*` env vars; 0 disables). Submissions: 5 per person per day |
| Sources | A plain web search per claim; results shown as returned (top 5, Parallel's order), social media and video sites excluded in the request. Site labels (official, news or research) are display only and never hide a result. The AI summary of the pages runs on Flash-Lite with the pages wrapped as untrusted data, and is dropped if it uses judging words |
| Content policy | Religious beliefs, claims about whole communities/castes/religions, private individuals and minors, live court cases, disasters in the first 48 h, satire: stored redacted and never shown |
| Reports | "Report a problem" on every statement goes to `/review`; a reviewer can hide a statement for everyone |
| YouTube data | Refreshed every 25 days by the daily maintenance cron (YouTube allows 30); videos no longer public are marked `removed` and hidden; no channel avatars stored |
| Privacy | Salted IP hashes only, for rate limits; deleted after 30 days by the maintenance cron |

All of these are covered by tests in `pipeline/tests/` (52 tests, offline).

## Going live

1. **Supabase**: create a project and run every migration in order (`supabase db push`, or the SQL editor):
   `0001`–`0015`. An existing database only needs the ones it's missing. `0012_sources_only.sql` hides old verdicts,
   merges hearsay/analogy/loaded-language into "other", adds sources, rate-limit and YouTube-refresh columns;
   `0013_plain_search_sources.sql` stores search results as returned (excerpt, rank, any site) and reopens claims
   that came back empty; `0014_source_summaries.sql` adds `claims.sources_summary` and `0015_sources_match.sql`
   adds `claims.sources_match`. If 0006–0011 were applied by hand
   (not through the CLI), apply 0012-0015 the same way:
   running `supabase migration up` would re-run 0006's backfill. Deploy order: migration, then pipeline, then web.
2. **Pipeline (Cloud Run)**: `cd pipeline && gcloud run deploy claimcheck-pipeline --source . --set-env-vars ...` with
   `GOOGLE_API_KEY`, `PARALLEL_API_KEY`, `YOUTUBE_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
   `PIPELINE_SHARED_SECRET`, optionally `MODEL_ARMOR_*`. Request timeout 60 min, CPU always allocated, and
   `--max-instances=1` (runs and the per-video lock live in memory).
3. **Web (Vercel)**: import `web/`, set the variables in `web/.env.example`, including `NEXT_PUBLIC_CONTACT_EMAIL`,
   `REVIEW_PASSWORD` and `CRON_SECRET`. `vercel.json` runs `/api/cron/maintenance` daily (allowed on Hobby).
4. **Gold set**: label ~20 videos in `pipeline/evals/gold_set.example.jsonl` format (statement, expected tag,
   optionally a site Check sources should find) and run `python -m evals.run_eval your_gold.jsonl`. Gates: extraction
   recall >= 80%, tag agreement >= 80%.

Model names, limits and prices are environment variables (`CLAIMCHECK_FAST_MODEL`,
`CLAIMCHECK_PRICES_JSON`, `CLAIMCHECK_SOURCES_PER_CLAIM`, `CLAIMCHECK_SUMMARY_MODEL`, `CLAIMCHECK_SUMMARIZE_SOURCES=0`, `CLAIMCHECK_SOURCES_ALL_MAX_SEARCHES`, `CLAIMCHECK_VIDEO_PROCESSING=static` for the fallback, ...); see `pipeline/claimcheck/config.py`.

## What has and hasn't been verified

Verified: all pipeline tests; live "Check sources" on real claims (5 sources and a Flash-Lite summary, about $0.0057); migrations 0012-0015 in PGlite (`node supabase/test_sources_migration.mjs`, with
`@electric-sql/pglite` installed) and on a local Supabase; web typecheck and production build; the pages in a real
browser against local data, including filing and resolving a report.

Not yet run against live services in this version: a full extraction with agentic video on a real URL (check that
the model doesn't silently fall back to static processing, and that tool-use tokens show up in the cost). Expect a
short shakedown on first live run.

Before launch: have a lawyer review the content policy, the reporting process and the IT Rules 2021 obligations
for digital publishers.
