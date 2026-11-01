-- Moves episodes from in_review to done once no pending verdicts remain. Called after each review.
create or replace function public.refresh_episode_review_status() returns void
language sql security invoker set search_path = '' as $$
  update public.episodes e set status = 'done'
  where e.status = 'in_review'
    and not exists (
      select 1 from public.claims c join public.verdicts v on v.id = c.verdict_id
      where c.episode_id = e.id and v.review_status = 'pending'
    );
$$;
revoke execute on function public.refresh_episode_review_status() from public, anon, authenticated;

-- Episodes whose tally should be recomputed after a reviewer changes a verdict.
create or replace function public.recompute_episode_tally(p_episode_id uuid) returns void
language sql security invoker set search_path = '' as $$
  update public.episodes e set tally = coalesce((
    select jsonb_object_agg(verdict, n) from (
      select v.verdict, count(*) as n from public.claims c join public.verdicts v on v.id = c.verdict_id
      where c.episode_id = p_episode_id and v.review_status in ('not_needed', 'approved', 'changed')
      group by v.verdict) t), '{}'::jsonb)
  where e.id = p_episode_id;
$$;
revoke execute on function public.recompute_episode_tally(uuid) from public, anon, authenticated;
