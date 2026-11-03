-- Sources only: ClaimCheck no longer publishes verdicts.
-- Every statement is tagged (claim, opinion, forecast, other). For a claim, a viewer can ask for sources: up to
-- three sentences copied word for word from official or established news pages, with links. Nothing is judged
-- true or false. Old verdict data is kept but no longer public, so this part can be undone.

-- ---------------------------------------------------------------------------
-- 1. Old verdicts: keep the rows, hide them from the public
-- ---------------------------------------------------------------------------
drop policy if exists verdicts_public_read on public.verdicts;
drop policy if exists citations_public_read on public.citations;
revoke select on public.verdicts, public.citations from anon, authenticated;

-- Episode columns that only made sense with verdicts.
revoke select (tally, not_checked, worthiness_score, auto_verify_status) on public.episodes from anon, authenticated;

-- ---------------------------------------------------------------------------
-- 2. Sources for a claim
-- ---------------------------------------------------------------------------
alter table public.claims add column if not exists sources_status text not null default 'not_eligible'
  check (sources_status in ('not_eligible', 'not_requested', 'queued', 'searching', 'done', 'failed'));
alter table public.claims add column if not exists sources_error text;          -- short public message
alter table public.claims add column if not exists sources_requested_at timestamptz;
alter table public.claims add column if not exists sources_checked_at timestamptz;

-- Factual claims that aren't redacted can have sources looked up.
update public.claims set sources_status = 'not_requested'
 where statement_type = 'factual_claim' and not_checked_reason is distinct from 'outside_policy' and policy_tier <> 'never';

alter table public.claims alter column verification_status set default 'not_eligible';

create table if not exists public.claim_sources (
  id uuid primary key default gen_random_uuid(),
  claim_id uuid not null references public.claims (id) on delete cascade,
  url text not null,
  title text,
  tier smallint not null check (tier in (1, 2)),   -- 1 = official / peer-reviewed, 2 = established news or research
  quote text not null,                             -- one sentence copied word for word from the page
  publish_date text,
  created_at timestamptz not null default now()
);
create index if not exists claim_sources_claim_id_idx on public.claim_sources (claim_id);
alter table public.claim_sources enable row level security;
create policy claim_sources_public_read on public.claim_sources for select to anon, authenticated
  using (exists (select 1 from public.claims c join public.episodes e on e.id = c.episode_id
                 where c.id = claim_sources.claim_id and e.status in ('processing', 'done', 'in_review')));
grant select on public.claim_sources to anon, authenticated;
grant all on public.claim_sources to service_role;

-- "Check sources for all claims" on one video: 'running' while it works, then null.
alter table public.episodes add column if not exists sources_batch_status text;
grant select (sources_batch_status) on public.episodes to anon, authenticated;

-- One row per press of a sources button, for rate limits (never readable with the anon key).
create table if not exists public.source_requests (
  id bigint generated always as identity primary key,
  claim_id uuid references public.claims (id) on delete cascade,
  episode_id uuid not null references public.episodes (id) on delete cascade,
  requester text not null,           -- salted hash of the IP, deleted after 30 days
  kind text not null check (kind in ('one', 'all')),
  outcome text not null default 'queued' check (outcome in ('queued', 'rejected', 'failed')),
  created_at timestamptz not null default now()
);
create index if not exists source_requests_requester_idx on public.source_requests (requester, created_at desc);
create index if not exists source_requests_created_idx on public.source_requests (created_at desc);
alter table public.source_requests enable row level security;
revoke all on public.source_requests from anon, authenticated;
grant all on public.source_requests to service_role;

-- ---------------------------------------------------------------------------
-- 3. Claims: only public columns are readable (hides verdict_id, verification state, tag notes, embeddings)
-- ---------------------------------------------------------------------------
revoke select on public.claims from anon, authenticated;
grant select (id, idx, episode_id, start_s, speaker, claim_text, context_quote, pestle_area, topic, topics,
              statement_type, policy_tier, not_checked_reason, created_at,
              sources_status, sources_error, sources_checked_at) on public.claims to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 4. Four neutral tags: hearsay, analogy and loaded language become "other"
-- ---------------------------------------------------------------------------
update public.claims set statement_type = 'other' where statement_type in ('hearsay', 'analogy', 'loaded_language');
update public.episodes e set statement_counts = coalesce((
  select jsonb_object_agg(statement_type, n) from (
    select statement_type, count(*) as n from public.claims c where c.episode_id = e.id group by statement_type) t
), '{}'::jsonb);

-- ---------------------------------------------------------------------------
-- 5. YouTube API data: refreshed every 30 days; videos YouTube no longer serves are hidden
-- ---------------------------------------------------------------------------
alter table public.episodes add column if not exists metadata_refreshed_at timestamptz not null default now();
alter table public.channels add column if not exists metadata_refreshed_at timestamptz not null default now();
alter table public.episodes drop constraint if exists episodes_status_check;
alter table public.episodes add constraint episodes_status_check
  check (status in ('queued', 'processing', 'in_review', 'done', 'skipped', 'failed', 'removed'));
-- Channel avatars came from the YouTube API and were never refreshed; the site shows initials instead.
update public.channels set avatar_url = null;

-- ---------------------------------------------------------------------------
-- 6. Reports: "Report a problem" on any statement
-- ---------------------------------------------------------------------------
alter table public.feedback add column if not exists kind text not null default 'other'
  check (kind in ('wrong_quote', 'wrong_speaker', 'wrong_tag', 'wrong_time', 'bad_source', 'other'));
create index if not exists feedback_open_idx on public.feedback (created_at) where status = 'open';
