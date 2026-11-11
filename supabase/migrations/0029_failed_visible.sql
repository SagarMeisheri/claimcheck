-- A video whose analysis failed (the AI service was out of credits, the cost cap was hit, the service restarted...) used to be hidden from the
-- public: its page said "That video isn't here" and the progress bar, which sees nothing, just stopped. Show it, so the page can say what happened
-- and offer a retry. Its claims stay hidden (the claims policy is unchanged).
drop policy if exists episodes_public_read on public.episodes;
create policy episodes_public_read on public.episodes for select to anon, authenticated
  using (status in ('queued', 'processing', 'in_review', 'done', 'skipped', 'failed'));
