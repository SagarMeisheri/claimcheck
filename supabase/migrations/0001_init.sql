-- ClaimCheck schema. Run with `supabase db push` or paste into the SQL editor.
-- Writes happen only with the service-role key (pipeline + web server actions).
-- The anon key can read published content only, enforced by RLS.

create extension if not exists vector with schema extensions;

-- ---------------------------------------------------------------------------
-- Channels
-- ---------------------------------------------------------------------------
create table public.channels (
  id uuid primary key default gen_random_uuid(),
  youtube_channel_id text not null unique,
  name text not null,
  track text not null check (track in ('politics', 'finance_health')),
  perceived_lean text not null default 'neutral' check (perceived_lean in ('supportive', 'critical', 'neutral')),
  rss_url text generated always as ('https://www.youtube.com/feeds/videos.xml?channel_id=' || youtube_channel_id) stored,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Episodes (one per YouTube video)
-- ---------------------------------------------------------------------------
create table public.episodes (
  id uuid primary key default gen_random_uuid(),
  youtube_video_id text not null unique,
  channel_id uuid references public.channels (id) on delete set null,
  title text,
  duration_s integer,
  published_at timestamptz,
  worthiness_score real,
  status text not null default 'queued'
    check (status in ('queued', 'processing', 'in_review', 'done', 'skipped', 'failed')),
  skip_reason text,
  tally jsonb not null default '{}'::jsonb,         -- {"supported": 3, "false": 1, ...}
  not_checked jsonb not null default '{}'::jsonb,   -- {"opinion": 4, "outside_policy": 2, ...}
  cost_usd numeric(10, 4),
  tokens_in bigint,
  tokens_out bigint,
  submitted_by text,                                -- hashed IP or user id; null for automatic runs
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index episodes_channel_id_idx on public.episodes (channel_id);
create index episodes_status_created_idx on public.episodes (status, created_at desc);

-- ---------------------------------------------------------------------------
-- Verdicts (shared across claims through the cache)
-- ---------------------------------------------------------------------------
create table public.verdicts (
  id uuid primary key default gen_random_uuid(),
  verdict text not null check (verdict in ('supported', 'misleading', 'false', 'outdated', 'disputed', 'unverifiable')),
  confidence real not null check (confidence between 0 and 1),
  reasoning text not null,
  evidence_grade text not null default 'not_applicable',
  model text,
  escalated boolean not null default false,
  downgrades jsonb not null default '[]'::jsonb,    -- guardrail rules that changed this verdict
  review_status text not null default 'not_needed'
    check (review_status in ('not_needed', 'pending', 'approved', 'changed')),
  reviewer text,
  reviewer_note text,
  reviewed_at timestamptz,
  recheck_after timestamptz,
  created_at timestamptz not null default now()
);
create index verdicts_pending_idx on public.verdicts (created_at) where review_status = 'pending';

-- ---------------------------------------------------------------------------
-- Claims
-- ---------------------------------------------------------------------------
create table public.claims (
  id uuid primary key default gen_random_uuid(),
  episode_id uuid not null references public.episodes (id) on delete cascade,
  idx integer not null,
  start_s integer not null default 0,
  speaker text,
  claim_text text not null,
  context_quote text,
  pestle_area text not null check (pestle_area in ('political', 'economic', 'social', 'technological', 'legal', 'environmental')),
  topic text,
  claim_type text not null check (claim_type in ('fact', 'opinion', 'prediction', 'anecdote')),
  policy_tier text not null check (policy_tier in ('normal', 'stricter', 'never')),
  checkworthiness real,
  not_checked_reason text,
  refers_to_visual boolean not null default false,
  embedding extensions.vector(768),
  verdict_id uuid references public.verdicts (id) on delete set null,
  created_at timestamptz not null default now(),
  unique (episode_id, idx)
);
create index claims_verdict_id_idx on public.claims (verdict_id);
create index claims_embedding_idx on public.claims using hnsw (embedding extensions.vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Citations
-- ---------------------------------------------------------------------------
create table public.citations (
  id uuid primary key default gen_random_uuid(),
  verdict_id uuid not null references public.verdicts (id) on delete cascade,
  url text not null,
  title text,
  tier smallint not null check (tier between 1 and 3),
  quote text not null,
  quote_check_passed boolean not null,
  retrieved_at timestamptz not null default now()
);
create index citations_verdict_id_idx on public.citations (verdict_id);

-- ---------------------------------------------------------------------------
-- Guardrail log, feedback, submissions (never readable with the anon key)
-- ---------------------------------------------------------------------------
create table public.guardrail_events (
  id bigint generated always as identity primary key,
  episode_id uuid references public.episodes (id) on delete cascade,
  claim_idx integer,
  stage text not null,
  rule text not null,
  action text not null check (action in ('blocked', 'downgraded', 'skipped', 'flagged')),
  detail text,
  created_at timestamptz not null default now()
);
create index guardrail_events_episode_idx on public.guardrail_events (episode_id);
create index guardrail_events_rule_idx on public.guardrail_events (rule, created_at desc);

create table public.feedback (
  id bigint generated always as identity primary key,
  claim_id uuid not null references public.claims (id) on delete cascade,
  suggested_verdict text,
  note text check (char_length(note) <= 2000),
  submitter text,
  status text not null default 'open' check (status in ('open', 'accepted', 'rejected')),
  created_at timestamptz not null default now()
);
create index feedback_claim_id_idx on public.feedback (claim_id);

create table public.submissions (
  id bigint generated always as identity primary key,
  submitter text not null,          -- salted hash of the IP
  youtube_video_id text not null,
  created_at timestamptz not null default now()
);
create index submissions_submitter_created_idx on public.submissions (submitter, created_at desc);

-- ---------------------------------------------------------------------------
-- updated_at trigger
-- ---------------------------------------------------------------------------
create or replace function public.set_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at = now();
  return new;
end;
$$;
create trigger episodes_set_updated_at before update on public.episodes
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Cache lookup: nearest verified claim above a similarity threshold.
-- Pending, unverifiable and expired verdicts are never reused.
-- ---------------------------------------------------------------------------
create or replace function public.match_verdict(
  query_embedding extensions.vector(768),
  similarity_threshold real default 0.92,
  max_age_days integer default 90
)
returns table (verdict_id uuid, verdict text, confidence real, reasoning text, evidence_grade text,
               review_status text, similarity real)
language sql stable security invoker set search_path = '' as $$
  select * from (
    select v.id, v.verdict, v.confidence, v.reasoning, v.evidence_grade, v.review_status,
           (1 - (c.embedding operator(extensions.<=>) query_embedding))::real as similarity
    from public.claims c
    join public.verdicts v on v.id = c.verdict_id
    where v.verdict <> 'unverifiable'
      and v.review_status in ('not_needed', 'approved', 'changed')
      and v.created_at > now() - make_interval(days => max_age_days)
      and c.embedding is not null
    order by c.embedding operator(extensions.<=>) query_embedding
    limit 1
  ) nearest
  where nearest.similarity >= similarity_threshold
$$;
revoke execute on function public.match_verdict(extensions.vector, real, integer) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- Row Level Security: anon reads published content only.
-- ---------------------------------------------------------------------------
alter table public.channels enable row level security;
alter table public.episodes enable row level security;
alter table public.verdicts enable row level security;
alter table public.claims enable row level security;
alter table public.citations enable row level security;
alter table public.guardrail_events enable row level security;
alter table public.feedback enable row level security;
alter table public.submissions enable row level security;

create policy channels_public_read on public.channels for select to anon, authenticated using (active);
-- perceived_lean is internal: hide the column from public roles.
revoke select on public.channels from anon, authenticated;
grant select (id, youtube_channel_id, name, track, active, created_at) on public.channels to anon, authenticated;

create policy episodes_public_read on public.episodes for select to anon, authenticated
  using (status in ('done', 'in_review'));
-- Cost and submitter are internal: expose only public columns.
revoke select on public.episodes from anon, authenticated;
grant select (id, youtube_video_id, channel_id, title, duration_s, published_at, worthiness_score, status,
              skip_reason, tally, not_checked, created_at, updated_at) on public.episodes to anon, authenticated;

create policy claims_public_read on public.claims for select to anon, authenticated
  using (exists (select 1 from public.episodes e where e.id = claims.episode_id and e.status in ('done', 'in_review')));

-- A verdict is public only once it needs no review or a person has signed it off.
create policy verdicts_public_read on public.verdicts for select to anon, authenticated
  using (review_status in ('not_needed', 'approved', 'changed'));

create policy citations_public_read on public.citations for select to anon, authenticated
  using (exists (select 1 from public.verdicts v where v.id = citations.verdict_id
                 and v.review_status in ('not_needed', 'approved', 'changed')));
-- guardrail_events, feedback, submissions: no policies => no public access.
