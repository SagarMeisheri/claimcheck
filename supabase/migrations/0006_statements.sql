-- Statement tagging and on-demand verification.
-- Every statement in a video is now stored with a type (factual claim, opinion, forecast, analogy,
-- loaded language, hearsay, other). Only a few factual claims are verified automatically; the rest
-- can be verified on request from the video page. Verdicts stay on the claim row, so a claim
-- verified once is shown to everyone.

-- ---------------------------------------------------------------------------
-- Claims: type, tag note and verification state
-- ---------------------------------------------------------------------------
alter table public.claims add column if not exists statement_type text not null default 'factual_claim'
  check (statement_type in ('factual_claim', 'opinion', 'forecast', 'analogy', 'loaded_language', 'hearsay', 'other'));
alter table public.claims add column if not exists tag_note text;  -- one line on why it got this tag
alter table public.claims add column if not exists verification_status text not null default 'not_requested'
  check (verification_status in ('not_eligible', 'not_requested', 'queued', 'verifying', 'verified', 'awaiting_review', 'failed'));
alter table public.claims add column if not exists verify_requested_at timestamptz;
alter table public.claims add column if not exists verify_error text;  -- short public message, never a stack trace

-- Backfill rows written before this migration.
update public.claims set statement_type = case claim_type
    when 'fact' then 'factual_claim' when 'opinion' then 'opinion' when 'prediction' then 'forecast' else 'other' end;
update public.claims c set verification_status = case
    when c.verdict_id is not null and exists (select 1 from public.verdicts v where v.id = c.verdict_id and v.review_status = 'pending')
      then 'awaiting_review'
    when c.verdict_id is not null then 'verified'
    when c.statement_type <> 'factual_claim' or c.policy_tier = 'never' or c.not_checked_reason = 'outside_policy' then 'not_eligible'
    else 'not_requested' end;
-- Lower-priority factual claims are no longer "not checked": they can be verified on request.
update public.claims set not_checked_reason = null
  where verification_status = 'not_requested' and not_checked_reason in ('not_prioritised', 'not_checkworthy', 'budget', 'error');

create index if not exists claims_episode_type_idx on public.claims (episode_id, statement_type);
create index if not exists claims_verifying_idx on public.claims (verify_requested_at)
  where verification_status in ('queued', 'verifying');

-- ---------------------------------------------------------------------------
-- Episodes: statement counts by type, for the home page breakdown card
-- ---------------------------------------------------------------------------
alter table public.episodes add column if not exists statement_counts jsonb not null default '{}'::jsonb;
grant select (statement_counts) on public.episodes to anon, authenticated;

update public.episodes e set statement_counts = coalesce((
  select jsonb_object_agg(statement_type, n) from (
    select statement_type, count(*) as n from public.claims c where c.episode_id = e.id group by statement_type) t
), '{}'::jsonb);

-- ---------------------------------------------------------------------------
-- Verify requests: one row per press of Verify, for rate limits (never readable with the anon key)
-- ---------------------------------------------------------------------------
create table if not exists public.verify_requests (
  id bigint generated always as identity primary key,
  claim_id uuid not null references public.claims (id) on delete cascade,
  episode_id uuid not null references public.episodes (id) on delete cascade,
  requester text not null,           -- salted hash of the IP, same as submissions
  outcome text not null default 'queued' check (outcome in ('queued', 'already_done', 'rejected', 'failed')),
  created_at timestamptz not null default now()
);
create index if not exists verify_requests_requester_idx on public.verify_requests (requester, created_at desc);
create index if not exists verify_requests_created_idx on public.verify_requests (created_at desc);
alter table public.verify_requests enable row level security;
revoke all on public.verify_requests from anon, authenticated;
grant all on public.verify_requests to service_role;
grant all on all sequences in schema public to service_role;
