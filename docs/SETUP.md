# Setup guide: run ClaimCheck on your machine

Everything runs locally: a Postgres database (Supabase in Docker), a Python service that analyses videos, and a Next.js
website. Nothing needs to be deployed. This guide takes about 20 minutes, most of it getting API keys.

```
 you ──► web app (Next.js, :3000) ──► pipeline (FastAPI + Google ADK, :8080) ──► Gemini, Parallel, YouTube APIs
              │  reads with the anon key              │  writes with the service-role key
              └────────────► Supabase (Postgres in Docker, API :55321) ◄────┘
```

The web app and the pipeline share a secret (`PIPELINE_SHARED_SECRET`), and both talk to the same local Supabase.

## 1. What you need installed

| Tool | Why | Check |
| --- | --- | --- |
| **Docker** (running) | Supabase runs in containers | `docker --version` |
| **Supabase CLI** | starts the local database and applies the migrations | `supabase --version` |
| **Python 3.11+** | the pipeline (the Dockerfile uses 3.12) | `python3 --version` |
| **Node 20+** and npm | the web app (Next.js 16) | `node --version` |
| **git** | to clone | |

The project was developed on macOS with Docker, Supabase CLI 2.x, Python 3.14 and Node 24.

## 2. What you need an account for

Three API keys. You can run the tests and open the web app without them, but analysing a video needs all three.

| Key | Where to get it | Used for |
| --- | --- | --- |
| `GOOGLE_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) | Gemini: reads the video, tags questions and answers, assesses sources, writes profiles and summaries |
| `PARALLEL_API_KEY` | [Parallel](https://parallel.ai) | web search for sources and for show and speaker profiles |
| `YOUTUBE_API_KEY` | Google Cloud Console: create a project, enable **YouTube Data API v3**, create an API key | video title, channel, duration and whether it is public and finished |

**Cost.** Each video has a cost cap (`CLAIMCHECK_MAX_COST_USD`; the code default is $3, the example env file sets $0.50
so first runs stay cheap). A web search costs about $0.005. Every model defaults to `gemini-3.5-flash-lite`. Check the
current prices on Google's and Parallel's pricing pages before you analyse a long video.

## 3. Get the code

```bash
git clone https://github.com/SagarMeisheri/claimcheck.git
cd claimcheck
```

## 4. Start the database

```bash
supabase start          # first run pulls Docker images, which takes a few minutes
supabase db reset       # applies migrations 0001-0029 to the local database
```

`supabase db reset` **wipes the local database** and rebuilds it. Use it on first setup or when you want a clean slate.
To add only new migrations to a database you want to keep, run `supabase migration up`.

Migration `0018` loads the 100 curated show profiles, so there is nothing else to seed. The app has no demo data: it
shows only the videos you submit.

Local ports (set in `supabase/config.toml`): API `55321`, Postgres `55322`, Studio `55323`. Studio is a web UI for
looking at the tables.

Print the values you need for the env files:

```bash
supabase status -o env
```

You will use three of them: `API_URL`, `ANON_KEY` and `SERVICE_ROLE_KEY`.

## 5. Set up the pipeline

```bash
cd pipeline
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Edit `pipeline/.env`:

```bash
GOOGLE_API_KEY=...                 # section 2
PARALLEL_API_KEY=...
YOUTUBE_API_KEY=...

SUPABASE_URL=http://127.0.0.1:55321        # API_URL from supabase status
SUPABASE_SERVICE_ROLE_KEY=...              # SERVICE_ROLE_KEY from supabase status
PIPELINE_SHARED_SECRET=devsecret           # any string; the web app must use the same one
CLAIMCHECK_MAX_COST_USD=0.50
```

Check the install. The tests need no keys and no network:

```bash
pytest                                      # 224 tests, about 2 seconds
```

Start the service and leave it running:

```bash
uvicorn claimcheck.server:app --port 8080
curl http://localhost:8080/healthz          # in another terminal: confirms it is up
```

Settings are read from `pipeline/.env`. A variable already set in your shell takes priority over the file.

## 6. Set up the web app

In a second terminal:

```bash
cd web
cp .env.example .env.local
npm install
```

Edit `web/.env.local`:

```bash
NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:55321    # API_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=...                  # ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=...                      # SERVICE_ROLE_KEY

PIPELINE_URL=http://localhost:8080
PIPELINE_SHARED_SECRET=devsecret                   # the same value as in pipeline/.env

SUBMITTER_SALT=any-random-string                   # salts the IP hash used for rate limits
REVIEW_USER=reviewer                               # login for the /review page
REVIEW_PASSWORD=pick-a-password
NEXT_PUBLIC_SITE_URL=http://localhost:3000
NEXT_PUBLIC_CONTACT_EMAIL=you@example.com          # shown on the How it works and Privacy pages
```

`CRON_SECRET` is only used by the daily maintenance job, so it is optional locally.

```bash
npm run dev                                 # http://localhost:3000
```

## 7. Analyse your first video

1. Open http://localhost:3000, paste a YouTube link and submit.
2. Use a **public, finished** video (not a live stream). Pick a short one, 10 to 20 minutes, for the first run.
3. The page shows a step checklist and fills in questions and answers as the model reads the video. Sources and
   evidence labels follow when the answers are checked.

You can also run a video from the command line, without the web app:

```bash
cd pipeline && . .venv/bin/activate
python -m claimcheck.cli "https://www.youtube.com/watch?v=VIDEO_ID"
```

Other commands, run from `pipeline/`:

```bash
python -m claimcheck.cli --sources CLAIM_ID          # sources for one answer (what the button does)
python -m claimcheck.cli --sources-all EPISODE_ID    # sources for every answer of a video
python -m claimcheck.cli --qa EPISODE_ID             # (re)write the Q&A index
python -m claimcheck.cli --tldr EPISODE_ID           # (re)write the podcast profile's TL;DRs
python -m claimcheck.cli --relink-channels           # attach channels to videos saved without one
```

Episode and claim IDs are the `id` columns in Studio (http://127.0.0.1:55323).

## 8. Optional settings

All live in `pipeline/.env`; the commented lines in `pipeline/.env.example` list the rest and
`pipeline/claimcheck/config.py` is the full reference.

| Variable | Effect |
| --- | --- |
| `CLAIMCHECK_AUTO_SOURCES=1` | look up sources for every answer automatically after a video is read, so nobody has to press "Check sources" |
| `CLAIMCHECK_MAX_COST_USD` | per-video cost cap |
| `CLAIMCHECK_FAST_MODEL`, `_SUMMARY_MODEL`, `_TAG_MODEL`, `_PROFILE_MODEL` | change the Gemini model used for each job |
| `CLAIMCHECK_VIDEO_PROCESSING=static` | fixed low-fps video reading instead of agentic reading |
| `CLAIMCHECK_BATCH_LOOKUPS=0` | one lookup per answer instead of the whole video at once |
| `CLAIMCHECK_SEARCH_LOCATION` | country code that searches are aimed at when the channel isn't a known show (default `in`) |

## 9. Pages worth opening

| URL | What it is |
| --- | --- |
| http://localhost:3000/v/VIDEO_ID | the video page: Q&A feed, player, podcast profile |
| http://localhost:3000/qa/VIDEO_ID | the shareable Q&A page of a finished video |
| http://localhost:3000/review | reviewer page (browser login: `REVIEW_USER` / `REVIEW_PASSWORD`): reports, stop and delete videos |
| http://127.0.0.1:55323 | Supabase Studio: browse the tables |

## 10. Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `supabase start` fails | Docker isn't running, or a port in 55321-55329 is taken. Start Docker; stop whatever holds the port |
| Web page errors about Supabase or shows no data | `web/.env.local` has a wrong or empty URL or key. Re-run `supabase status -o env` and copy them again. Restart `npm run dev` after editing env files |
| Submitting a video does nothing or errors | The pipeline isn't running on `PIPELINE_URL`, or the two `PIPELINE_SHARED_SECRET` values differ |
| `500 PIPELINE_SHARED_SECRET is not configured` | The variable is empty in `pipeline/.env` |
| A video ends as **failed** with a reason | The page shows the reason and a retry button. Common ones: a key is missing or out of credit, the video is private or live, or the cost cap was hit. Raise `CLAIMCHECK_MAX_COST_USD` or pick a shorter video |
| Answer cards update late | Realtime isn't running, so the page falls back to polling. That is harmless |
| Videos saved with no channel or show profile | Run `python -m claimcheck.cli --relink-channels` once |
| Want a clean slate | `supabase db reset` (from the repo root) deletes every video and profile |
| `pytest` fails to import | Activate the venv (`. .venv/bin/activate`) and run `pip install -e ".[dev]"` again |

## 11. Stop everything

`Ctrl+C` in the uvicorn and `npm run dev` terminals, then `supabase stop` from the repo root. Your local data is kept
until you run `supabase db reset`.

For deploying to Cloud Run and Vercel, see "Going live" in the main [README](../README.md).
