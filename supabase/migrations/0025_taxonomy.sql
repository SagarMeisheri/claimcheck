-- The Q&A taxonomy: profiles first, incentive tags per person, and one tagging chain per answer.
--
--   claims.qa_tags = {"question": {"type", "p", "spoken"},       factual | explanatory | experiential | evaluative | speculative | challenging
--                     "answer":   {"type", "p"},                  direct | narrative | structured | pivot | evasive
--                     "claim":    {"type", "p"},                  objective_fact | anchored_opinion | pure_opinion | prediction
--                     "grounding": {"label", "p", "evidence", "basis"},  grounded | plausible | contradicted | exempt | ungrounded
--                     "match": {"label", "p"}, "flags": [...], "conflict": {"kind", "disclosure"}, "chain": "..."}
--   (agents/qa_tags.py). It replaces claims.question_analysis and claims.research.tags / research.correctness, which stop being written.
--
--   episode_speakers.incentives = {tag: {"p", "basis": {"text", "url", "site"}}}, the documented incentive tags of a person for this
--   video (agents/profile_tags.py). episode_speakers.incentives_internal holds the two judgement tags (access_preserving,
--   audience_captured): they steer the skepticism rules and are never sent to the browser.
--
--   episodes.interaction = {"dynamic": "promotional" | "neutral" | "adversarial", "p"}: how the host and guest dealt with each other.
--
--   speakers.profile_version / creators.profile_version: 2 for the comprehensive profiles (agents/speakers.py, agents/creators.py).
--   An older profile is rebuilt only when a new video meets that person or show.

alter table public.claims add column if not exists qa_tags jsonb;
grant select (qa_tags) on public.claims to anon, authenticated;

alter table public.episodes add column if not exists interaction jsonb;
grant select (interaction) on public.episodes to anon, authenticated;

alter table public.episode_speakers add column if not exists incentives jsonb;
alter table public.episode_speakers add column if not exists incentives_internal jsonb;
revoke select on public.episode_speakers from anon, authenticated;
grant select (episode_id, label, speaker_id, role, statements, incentives) on public.episode_speakers to anon, authenticated;

alter table public.speakers add column if not exists profile_version integer not null default 1;
alter table public.speakers add column if not exists profiled_at timestamptz;
grant select (profile_version) on public.speakers to anon, authenticated;
alter table public.creators add column if not exists profile_version integer not null default 1;
alter table public.creators add column if not exists profiled_at timestamptz;
grant select (profile_version) on public.creators to anon, authenticated;

-- A v2 profile carries the profile writer's incentive tags: profile.incentives (shown) and profile.incentives_internal (never shown).
-- The public views drop the internal ones.
alter table public.speakers drop column if exists public_profile;
alter table public.speakers add column public_profile jsonb
  generated always as (profile - 'known_positions' - 'criticisms' - 'incentives_internal') stored;
alter table public.creators drop column if exists public_profile;
alter table public.creators add column public_profile jsonb
  generated always as (profile - 'biases' - 'controversies' - 'criticism' - 'incentives_internal') stored;
grant select (public_profile) on public.speakers to anon, authenticated;
grant select (public_profile) on public.creators to anon, authenticated;
