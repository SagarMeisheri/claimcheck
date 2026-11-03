-- Subject tags: 1-2 per statement, from the fixed list in pipeline/claimcheck/policy.yaml (topics:).
-- Shown as filter chips under the statement-type tabs. The old single `topic` column stays (first tag).
alter table public.claims add column if not exists topics text[] not null default '{}';

-- Backfill older rows from their single topic. Redacted (outside-policy) statements keep no tags.
update public.claims
   set topics = array[topic]
 where topics = '{}' and topic is not null and topic <> '' and not_checked_reason is distinct from 'outside_policy';

create index if not exists claims_topics_idx on public.claims using gin (topics);
