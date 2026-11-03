> **Superseded (3 Nov 2026):** ClaimCheck no longer publishes verdicts. It now tags statements and shows sources for claims; see `README.md`. This report describes the earlier verdict-based version.

# ClaimCheck: what it is, how it works, and what needs attention

*Report written 3 Nov 2026 from a full read of the code at commit `b17d6fb`, plus web research on the outside services it depends on.*

---

## 1. In one paragraph

ClaimCheck takes a YouTube video (mainly long Indian political, finance and health podcasts, panels and interviews) and breaks it into **every substantive statement**, each with a timestamp. Each statement is tagged as one of: **claim, opinion, forecast, hearsay, analogy, loaded language, or other**. Only "claims" (checkable facts about the past or present) can be fact-checked. Checking happens **when a viewer asks**: press **Verify** on one claim, or **Verify all claims** for a whole video. The verifier searches the web, an AI judge decides **True / False / Unverifiable** and must quote the exact sentence it relied on, and plain code then checks that work: the quote must really be in the source, the numbers must match, and the source must be recognised. Every False verdict is held for a human reviewer before anyone sees it. A verdict is saved once and shown to everyone.

---

## 2. The three parts

```
web/        Next.js 16 site (Vercel)       what viewers see; rate limits; reviewer page; RSS cron
pipeline/   Python service (Cloud Run)     Google ADK agents + Gemini + Parallel web search + guardrails
supabase/   Postgres (Supabase)            11 migrations; row-level security; pgvector verdict cache
```

```
 Viewer ──► Next.js (web) ──server actions──► Pipeline (FastAPI, 1 instance)
               │  reads via anon key (RLS)          │  writes via service key
               ▼                                    ▼
            Supabase Postgres  ◄────────────────────┘
                                                    │
                     Gemini (video reading, judging, embeddings)
                     Parallel (web search + page extract)
                     YouTube Data API (1 metadata call per video)
```

- **Only code writes to the database.** The AI agents have no write tools; they return structured JSON that code checks and saves.
- **The public site reads with the anon key**, so Postgres row-level security decides what is visible (verdicts waiting for review are hidden, and internal columns like cost and channel "lean" are never exposed).

---

## 3. How a video is processed

### 3a. First pass: read and tag (no fact-checking)

Triggered by `/submit` (5 per person per day), the home-page box, or the RSS cron (curated channels, every 10 min on Vercel). Runs as an ADK `SequentialAgent` (`pipeline/claimcheck/agents/pipeline.py`):

| Step | Type | What it does |
|---|---|---|
| IngestGate | code | One YouTube API call. Rejects private/unlisted, live, Shorts, under 5 min. Flags injection-like text in title/description and wraps it as "untrusted". |
| TriageAgent | LLM (Gemini 3.8 Flash) | Scores "worthiness" 0–1, PESTLE topic mix, share of "never check" content. |
| TriageGate | code | Skips the video if worthiness < 0.5 or > 30% never-check content. |
| ExtractorAgent | LLM (Gemini 3.8 Flash, agentic video) | Gemini watches the YouTube URL directly and returns up to 150 statements with timestamp, speaker, verbatim quote, type, 1–2 subject tags, policy tier, plus a 2–3 sentence summary. |
| (streaming) | code | While the extractor is still writing, each finished statement is parsed out of the partial JSON and saved, so the page fills in live with a progress bar. |
| ClaimFilter | code | Enforces the 150 cap; re-applies the content policy in code (tiers can only get stricter); never-check statements are stored redacted. |
| Publisher | code | Final save; per-type counts, summary, cost. |

### 3b. Verify one claim (the Verify button)

1. **Web app** (`web/app/actions.ts`): checks the claim is eligible, applies rate limits (10 per person per day by salted IP hash, 120 per hour site-wide), marks it `queued`, calls the pipeline.
2. **Pipeline** (`agents/on_demand.py`): one verification per video at a time (in-memory lock) so the **$3 per-video cost cap** can't be overspent.
3. **Cache**: embeds the claim; if a similar claim (cosine ≥ 0.92, < 90 days old, already published) has a verdict, reuse it for free.
4. **ADK Workflow** (`agents/verifier.py`): `plan` (LLM proposes 3 searches: news source, corroboration, counter-evidence) → `clamp` (code: max 3, no retries) → `search` (3 Parallel searches at once, top 3 pages each fetched in full) → `judge` (Gemini 4 Argon: TRUE / FALSE / UNVERIFIABLE + explanation + exact quotes).
5. **Code checks** (`guardrails/verdict_checks.py`), which can only downgrade, never upgrade:
   - each quote must appear (after normalising) in the fetched page text, at least 25 characters
   - a True claim's numbers must appear in the quotes (understands lakh, crore, %, ±5%)
   - True/False needs at least one tier-1 (official) or tier-2 (major news) source
   - False needs confidence ≥ 0.8
   - reasoning containing words like "lied" or "propaganda" is replaced with a neutral template
   - a 0–100 "truthfulness score" is computed in code (none for Unverifiable)
6. **Human review**: every False verdict waits for a reviewer (`/review`, HTTP basic auth). Until then it's hidden by RLS and the claim shows "With a reviewer".

### 3c. Verify all claims (newest feature, last two commits)

`agents/video_verifier.py`: a cheaper, batched loop for a whole video (up to 40 claims, 15 searches per press; 3 presses per person per day).

1. Cache hits are published first.
2. **One** lite-model call triages every claim: `knowledge` (stable well-known fact), `search`, or `skip`, and groups claims one search can settle together.
3. Code overrides the model: only normal-tier claims with no numbers (years are allowed) may use the knowledge route.
4. In parallel: one general-knowledge call for the easy claims (published as True only if the model is ≥ 0.9 confident, labelled "no source searched"), and one search + one batch judge per group.
5. One follow-up search for claims still unsettled, if budget remains. Anything left goes back to "not requested".

Each verdict appears on the page the moment it's saved.

---

## 4. Guardrails at a glance

| Risk | How it's handled | Where |
|---|---|---|
| Runaway cost | $3/video cap checked before every model call (ADK plugin); searches costed too | `guardrails/budget.py`, `tools/evidence.py` |
| Prompt injection from video/pages | Regex screen removes instruction-like lines; everything untrusted is wrapped in `<<<UNTRUSTED>>>` markers; optional Google Model Armor | `guardrails/injection.py` |
| Bad/blocked sources | Social media and YouTube never used; source tier computed from the URL, not the model | `policy.yaml`, `policy.py` |
| Hallucinated quotes/numbers | Quote-in-source and number checks in code | `verdict_checks.py` |
| Sensitive topics | Religion, community/caste generalisations, private people, minors, live court cases, disasters < 48 h, satire: redacted, never checked | `policy.yaml`, `stages.py` |
| Wrong False verdicts | Every False waits for a person | `policy.needs_review` |
| Political balance | Curated channels tagged supportive/critical/neutral (internal only); cron picks the side that is behind; `/balance` page | `scripts/seed_channels.py`, `api/cron/poll` |
| Abuse of buttons | Per-person and site-wide rate limits with salted IP hashes | `web/app/actions.ts` |

---

## 5. Screens

| Route | What it is |
|---|---|
| `/` | Feed of videos: thumbnail, summary, verdict strip, "X of Y verified claims supported", a paged carousel of statements by type, Verify all, verdict filter chips. Tabs: Latest, Topics, Following (stored in the browser). Search and PESTLE filters. |
| `/v/VIDEO_ID` | Watch-and-check: YouTube player (loads only on tap, nocookie host, 1.5x speed and 75% captions by default) with a tick track of statements underneath; filter chips by type, subject and verdict; "Watch 20 s" per statement; "Play verified claims in order"; J/K keys. |
| `/c/CHANNEL_ID` | A channel's checked videos and tally. |
| `/submit`, `/balance`, `/method` | Submit a video; political balance stats; public "How we check" page. |
| `/review` | Password-protected: approve or change pending verdicts; stop or delete videos. |
| `/api/og/[id]` | Share image (1200×630) for one verdict. |

---

## 6. Stack and outside services (checked on the web)

| Thing | In the code | What I found |
|---|---|---|
| Google ADK | `google-adk` 2.13.0 installed; uses the new `Workflow` graph API with `@node(parallel_worker=True)` | ADK 2.x deprecates `SequentialAgent` in favour of `Workflow`; the first-pass pipeline still uses `SequentialAgent` (README already notes the warning). Behaviour differs between 2.x minor versions, and `pyproject.toml` has no upper bound (`>=2.8`). |
| Gemini models | `gemini-3.8-flash` (triage, extract, plan), `gemini-4-argon` (judge), `gemini-3.5-flash-lite` (Verify all), `gemini-embedding-001` | All four model IDs exist on Google's pricing page. **Prices in `config.py` are partly wrong. See finding 1.** |
| Agentic video | `types.Part(media_processing=AGENTIC)` via `generateContent`, `google-genai` 2.34 | Google's docs list 3.8 Flash as supported. Their current examples use the Interactions API with `processing: "agentic"`. A developer write-up reports that misconfiguration falls back silently to the more expensive static mode. Not yet run live. |
| Parallel (web search) | `search(mode="fast")` + `extract(full_content=True)` | Search is $0.005/request and Extract $0.001/URL, which matches `config.py`. |
| Next.js | 16.4.3, `proxy.ts` for reviewer auth | Next.js 16 renamed `middleware.ts` to `proxy.ts`, so this is correct. |
| YouTube | Data API (1 unit/video), IFrame player, RSS | YouTube policies forbid drawing over the player and require at least 200×200. The code follows both. The policies also forbid "modifying standard playback". Defaulting every video to 1.5x is worth a check against that wording. |

---

## 7. State of the project

- **History** (19 commits): it began by auto-verifying a prioritised set of claims. It then moved to "tag everything, verify on demand", rebuilt verification as a parallel ADK workflow, added live streaming of statements, subject tags, a carousel, and most recently a "Verify all claims" batch verifier and verdict filter chips.
- **Tests**: `pytest` passes **69/69** (guardrails, policy, tagging, on-demand, both verifiers), with no API keys needed. There are no web tests in the repo (`web/tests/` is referenced in the README but doesn't exist).
- **Not yet run against live services** (README says so too): Gemini agentic video on a real URL, Parallel, YouTube API, Supabase in production, Model Armor.

---

## 8. Findings

Ranked by how much they matter. All were confirmed in the code unless marked **risk** (meaning it's likely but needs a live test to confirm).

### Should fix

**1. The $3 cost cap undercounts real spend.**
- `config.py:75-80` prices "flash-lite" at $0.10/$0.40 per M tokens. Google lists `gemini-3.5-flash-lite` at **$0.30 / $2.50**, which is 3× and 6× higher. Verify all runs mostly on this model.
- Gemini 4 Argon is coded as $2.50/$15. It is $2/$10 today but **doubles to $4/$20 on 1 Dec 2026**. Gemini 3.8 Flash ($0.75/$3.75, correct today) **doubles on 1 Jan 2027**.
- `guardrails/budget.py:45-47` counts prompt, output and thinking tokens but ignores `tool_use_prompt_token_count`. Google's docs say agentic video bills loaded frames, audio and transcripts as tool-use tokens, so **risk:** the biggest cost (reading the video) may be mostly uncounted.
- Embedding calls are never costed (small).

**2. A reviewer changing a verdict leaves the old score and correction.** `web/app/actions.ts:259-271` updates `verdict` but not `score` or `correction`. A False verdict scored 8/100 that a reviewer changes to True will display "True · 8/100" with the old correction text. Recompute or clear both on change.

**3. "Most check-worthy" ordering does nothing.** Nothing writes `checkworthiness` any more (the prioritiser was removed in `45fa5c7`), so it is always null. As a result:
- Verify all takes the **first 40 claims by time**, not the most important. In a 2-hour podcast, later claims never get picked.
- The carousel's "strongest supported claim first" is really "first one found".

**4. The public "How we check" page (`web/app/method/page.tsx`) and the README describe things the code no longer does.** For a fact-checking site, this is the kind of gap critics will look for.
- It says a False verdict needs "a second independent check". `policy.yaml` has `false_requires_second_judge: false`.
- It says verification "searches official sources first: RBI, MoSPI, PIB…". All three planned searches are now `scope: "open"` (`prompts.py:90-94`), and Verify all also searches the open web. The per-topic official-domain lists are effectively unused.
- It says "Nothing is verified automatically". Verify all can publish **True from the model's general knowledge with no source** (`video_verifier.py:173-177`). These verdicts are labelled "no source searched", but they skip every source check, and the cache (`match_verdict`) doesn't filter by `basis`, so **a memory-only verdict can be reused for similar claims in other videos**.
- It describes Disputed / Misleading / Outdated verdicts. The judge can now only return TRUE / FALSE / UNVERIFIABLE, so those three appear only if a reviewer picks them. The "political Misleading/Disputed waits for review" rule can never fire.
- README: says "4 searches per claim" (the code uses 3) and "stricter-tier claims need a tier-1 source" (replaced by a news-source rule in `34c2d36`). It lists migrations only up to 0006 (there are 11) and points to a `tests/ui.test.js` that doesn't exist.

**5. The eval script can't measure verdicts any more.** `evals/run_eval.py` calls `run_episode`, which no longer verifies anything (unless `CLAIMCHECK_AUTO_VERIFY=1`). "Verdict agreement" will read near 0%, and the launch gates (≥ 80% agreement, ≤ 3% False/True confusion) can't be checked. It needs to call the verifier after extraction.

### Worth knowing

**6. Risk: the cache may reuse a verdict for a claim with different numbers.** A 0.92 embedding similarity can match "GDP grew 7.2% in FY24" with "GDP grew 8.2% in FY24". A cache hit skips the number check. A cheap fix is to also require that the numbers in both claim texts match before reusing.

**7. Risk: agentic video isn't proven.** It is wired through `generateContent` + `media_processing`, while Google's current docs show the Interactions API. Silent fallback to static would raise cost without any error. This is the first thing to test live; log `tool_use_prompt_token_count` and thought tokens on the first runs.

**8. Single-instance design.** Running jobs and the per-video lock live in memory, so Cloud Run must stay at `--max-instances=1`. A restart marks in-flight work as failed. That is fine for an MVP; moving the lock into Postgres (e.g. an advisory lock) would lift it. The Supabase Python client is synchronous and blocks the event loop during writes (already noted in the README).

**9. Editorial: PIB is a tier-1 "official" source.** PIB is the government's press office, and it was the body designated as the government Fact Check Unit under the 2023 IT Rules amendment. The Bombay High Court struck that amendment down, and as of March 2026 the Supreme Court is hearing the Centre's appeal without staying the ruling. For a product that promises balance, ranking government press releases alongside statistical bodies like MoSPI may draw criticism. Consider tier 2 for PIB, or require a data source for political claims.

**10. Smaller items**
- `VideoCard.tsx` shows every visitor a "Stop or remove" link during checking, but it leads to the password-protected `/review`.
- `@app.on_event("startup")` is deprecated in FastAPI (use lifespan).
- Basic-auth password comparison in `proxy.ts` and `actions.ts` isn't constant-time.
- The `0010_topics.sql` comment mentions a fixed topic list; topics are now free-form.
- India's DPDP Rules: most data-fiduciary duties start **13 May 2027**. Salted IP hashes are stored for rate limiting, so a short privacy notice and a retention limit on `submissions`/`verify_requests` would be sensible before then.

---

## 9. Rough cost per Verify press (estimate)

One claim, at today's prices: 3 searches ($0.015) + up to 9 page extracts ($0.009) + the Argon judge reading up to ~9 × 15,000 characters (~34k tokens, ~$0.07), plus a small planner call. That comes to **about $0.10 per claim today and about $0.17 after 1 Dec**. A $3 video budget therefore covers roughly 15–30 single verifications after the first pass. The extraction cost of a long video is the big unknown until it runs live (see findings 1 and 7).

---

## 10. Suggested next steps (in order)

1. Fix the price table, count tool-use tokens, and do one live run with logging to see real extraction cost (findings 1, 7).
2. Fix the reviewer score/correction bug (finding 2).
3. Either bring back a check-worthiness score (e.g. from the triage step of Verify all) or sort by something real (finding 3).
4. Rewrite `/method` and the README to match the code, and decide whether memory-only True verdicts should exist and be cacheable (finding 4).
5. Update the eval to run verification, then label the 20-video gold set (finding 5).
6. Add a number-match condition to cache reuse (finding 6).

---

## Sources

- [Gemini API pricing (official)](https://aistudio.google.com/docs/pricing)
- [Gemini video understanding / agentic processing (official)](https://aistudio.google.com/docs/video-understanding?hl=en)
- [Video understanding, Google Cloud docs](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/video-understanding)
- [Gemini agentic video: 4 hidden prerequisites (DEV Community)](https://dev.to/gde/ai-in-action-gemini-agentic-video-4-hidden-prerequisites-and-my-line-bot-integration-process-582f)
- [Gemini API pricing roundup (Morph)](https://www.morphllm.com/gemini-api-pricing)
- [ADK 2 Orchestration codelab](https://codelabs.developers.google.com/adk2/instructions)
- [adk-python PR #6962: Sequential/Parallel/Loop agents deprecated](https://github.com/google/adk-python/pull/6962)
- [adk-python issue #5872: Workflow can't be a sub_agent](https://github.com/google/adk-python/issues/5872)
- [Parallel pricing](https://parallel.ai/pricing)
- [Switching from Tavily to Parallel Search API](https://parallel.ai/articles/tavily-to-parallel-search-api)
- [Next.js 16 proxy basics (Vercel)](https://vercel.com/academy/nextjs-foundations/proxy-basics)
- [Next.js 16 proxy.ts migration (DEV Community)](https://dev.to/iurii_rogulia/nextjs-16-proxyts-migration-from-middlewarets-28km)
- [YouTube API Services: Required Minimum Functionality](https://developers.google.com/youtube/terms/required-minimum-functionality)
- [Complying with YouTube's Developer Policies](https://developers.google.com/youtube/terms/developer-policies-guide)
- [Supreme Court hears Centre's appeal on Fact Check Unit (Storyboard18)](https://www.storyboard18.com/how-it-works/supreme-court-agrees-to-hear-centre-appeal-on-it-rules-amendment-on-fact-check-unit-91843.htm)
- [SC issues notice, refuses stay on FCU judgment (IFF)](https://internetfreedom.in/supreme-court-of-india-issued-notice-but-refused-any-stay-in-union-of-indias-challenge-to-the-bombay-high-court-judgement-holding-fact-check-unit-to-be-ultra-vires/)
- [DPDP Rules 2025 timeline (Taxmann)](https://www.taxmann.com/post/blog/analysis-indias-dpdp-act-and-rules/)
- [DPDP Rules 2025 framework (TCSA)](https://www.tcsa.in/frameworks/dpdp/rules-2025)
