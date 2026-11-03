-- Sources are now whatever one web search returns for a claim (top 5, in the search engine's order), with the
-- excerpt the search took from each page. No model picks sentences and no site is filtered out afterwards, so:
--   quote  -> excerpt   (it is page text chosen by the search, shown as an excerpt rather than a checked quote)
--   tier   any of 1-3   (a display label only: official, established news/research, other)
--   rank                (the search engine's order, most relevant first)
-- Claims that came back empty under the old filters are reopened so they can be looked up again.

alter table public.claim_sources rename column quote to excerpt;
alter table public.claim_sources alter column excerpt set default '';
alter table public.claim_sources drop constraint if exists claim_sources_tier_check;
alter table public.claim_sources add constraint claim_sources_tier_check check (tier between 1 and 3);
alter table public.claim_sources add column if not exists rank smallint not null default 0;
drop index if exists claim_sources_claim_id_idx;
create index if not exists claim_sources_claim_rank_idx on public.claim_sources (claim_id, rank);

update public.claims c set sources_status = 'not_requested', sources_checked_at = null
 where c.sources_status = 'done'
   and not exists (select 1 from public.claim_sources s where s.claim_id = c.id);
