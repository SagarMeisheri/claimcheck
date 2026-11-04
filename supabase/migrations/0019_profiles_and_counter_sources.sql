-- Creator and speaker context for analysis and source checks, sections, and a second ("other side") source search.

-- ---------------------------------------------------------------------------------------------------------------
-- Fix: channels created automatically from a video's metadata failed since `track` was dropped from the insert
-- (0016-era code), so those videos showed "Submitted video" instead of their channel. Tracks are no longer used.
-- ---------------------------------------------------------------------------------------------------------------
alter table public.channels alter column track drop not null;

-- ---------------------------------------------------------------------------------------------------------------
-- Creators: a neutral summary, and a public view of the profile without the bias/criticism notes.
-- The full profile stays internal: it only steers source searches.
-- ---------------------------------------------------------------------------------------------------------------
alter table public.creators add column if not exists summary text;  -- 1-2 neutral sentences: who hosts it, what it covers
alter table public.creators add column if not exists public_profile jsonb
  generated always as (profile - 'biases' - 'controversies' - 'criticism') stored;

-- Written from the neutral parts of the profile (hosts, what the show is known for); no model involved.
update public.creators
   set summary = podcast || ', hosted by ' || (profile->>'hosts') || '. ' || (profile->>'known_for')
 where summary is null;

drop policy if exists creators_public_read on public.creators;
create policy creators_public_read on public.creators for select to anon, authenticated using (true);
grant select (id, rank, podcast, youtube_channel_name, youtube_handles, market, country, summary, public_profile)
  on public.creators to anon, authenticated;

-- ---------------------------------------------------------------------------------------------------------------
-- Speakers: one profile per named person, built from a web search the first time they appear, then reused.
-- name_key is the lower-cased name. status 'not_found' remembers names a search couldn't pin to one public person.
-- profile keys: role, background, affiliations, topics, known_positions, criticisms. The last two are internal.
-- ---------------------------------------------------------------------------------------------------------------
create table if not exists public.speakers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  name_key text not null unique,
  status text not null default 'ready' check (status in ('ready', 'not_found')),
  summary text,                                   -- 1-2 neutral sentences
  profile jsonb not null default '{}'::jsonb,
  public_profile jsonb generated always as (profile - 'known_positions' - 'criticisms') stored,
  sources jsonb not null default '[]'::jsonb,     -- [{url, title}] the profile was written from
  creator_id uuid references public.creators (id) on delete set null,  -- set when the speaker hosts a known show
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
drop trigger if exists speakers_set_updated_at on public.speakers;
create trigger speakers_set_updated_at before update on public.speakers
  for each row execute function public.set_updated_at();
alter table public.speakers enable row level security;
drop policy if exists speakers_public_read on public.speakers;
create policy speakers_public_read on public.speakers for select to anon, authenticated using (status = 'ready');
grant select (id, name, status, summary, public_profile, sources, creator_id, created_at) on public.speakers to anon, authenticated;
grant all on public.speakers to service_role;

-- Who speaks in a video: the label the extractor used (claims.speaker) and the profile it maps to.
create table if not exists public.episode_speakers (
  episode_id uuid not null references public.episodes (id) on delete cascade,
  label text not null,
  speaker_id uuid references public.speakers (id) on delete set null,
  role text check (role in ('host', 'guest')),
  statements integer not null default 0,
  primary key (episode_id, label)
);
create index if not exists episode_speakers_speaker_idx on public.episode_speakers (speaker_id);
alter table public.episode_speakers enable row level security;
drop policy if exists episode_speakers_public_read on public.episode_speakers;
create policy episode_speakers_public_read on public.episode_speakers for select to anon, authenticated
  using (exists (select 1 from public.episodes e where e.id = episode_speakers.episode_id
                 and e.status in ('processing', 'done', 'in_review')));
grant select on public.episode_speakers to anon, authenticated;
grant all on public.episode_speakers to service_role;

-- ---------------------------------------------------------------------------------------------------------------
-- Episodes: the matched creator, and sections (what was being discussed, and when).
-- sections: [{"idx": 0, "start_s": 0, "end_s": 610, "title": "...", "summary": "..."}]
-- progress (0005) now also carries "steps": [{"key", "label", "status": "done" | "running" | "pending" | "skipped"}].
-- ---------------------------------------------------------------------------------------------------------------
alter table public.episodes add column if not exists creator_id uuid references public.creators (id) on delete set null;
alter table public.episodes add column if not exists sections jsonb not null default '[]'::jsonb;
grant select (creator_id, sections) on public.episodes to anon, authenticated;

-- ---------------------------------------------------------------------------------------------------------------
-- Claims: section, and how its sources were looked up.
-- sources_route: the classifier's decision. 'skip' = not looked up automatically (background, self-description,
-- nothing specific); 'related' = one search; 'data' / 'contested' = also a second search for different figures or
-- other perspectives. sources_triage keeps the classifier's probabilities (internal, for tuning).
-- counter_summary: neutral summary of the second search's excerpts.
-- ---------------------------------------------------------------------------------------------------------------
alter table public.claims add column if not exists section_idx integer;
-- One neutral line from the extractor on what was being discussed when the statement was made.
alter table public.claims add column if not exists statement_context text;
grant select (statement_context) on public.claims to anon, authenticated;
alter table public.claims add column if not exists sources_route text
  check (sources_route in ('skip', 'related', 'data', 'contested'));
alter table public.claims add column if not exists sources_triage jsonb;
alter table public.claims add column if not exists counter_summary text;
grant select (section_idx, sources_route, counter_summary) on public.claims to anon, authenticated;

-- Which search found a source: 'related' (the statement's own subject) or 'counter' (different figures / views).
alter table public.claim_sources add column if not exists kind text not null default 'related'
  check (kind in ('related', 'counter'));

-- Videos already analysed from a known show get their creator.
update public.episodes e
   set creator_id = cr.id
  from public.channels ch, public.creators cr
 where e.channel_id = ch.id and ch.youtube_channel_id = any(cr.youtube_channel_ids) and e.creator_id is null;
