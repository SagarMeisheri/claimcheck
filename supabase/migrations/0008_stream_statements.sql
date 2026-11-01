-- Statements are saved while the extractor is still reading the video, so the video page and the home
-- carousel can show them before the check finishes. Only the 'processing' status is added.
drop policy if exists claims_public_read on public.claims;
create policy claims_public_read on public.claims for select to anon, authenticated
  using (exists (select 1 from public.episodes e where e.id = claims.episode_id and e.status in ('processing', 'done', 'in_review')));
