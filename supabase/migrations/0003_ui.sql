-- UI redesign: channel avatars, and public visibility of in-progress / skipped episodes
-- (their pages show status and the reason; claims stay hidden until done or in review).

alter table public.channels add column if not exists avatar_url text;
grant select (avatar_url) on public.channels to anon, authenticated;

drop policy if exists episodes_public_read on public.episodes;
create policy episodes_public_read on public.episodes for select to anon, authenticated
  using (status in ('queued', 'processing', 'in_review', 'done', 'skipped'));

-- Claims stay visible only for finished or in-review episodes (unchanged policy, restated for clarity).
drop policy if exists claims_public_read on public.claims;
create policy claims_public_read on public.claims for select to anon, authenticated
  using (exists (select 1 from public.episodes e where e.id = claims.episode_id and e.status in ('done', 'in_review')));

create index if not exists claims_episode_start_idx on public.claims (episode_id, start_s);
