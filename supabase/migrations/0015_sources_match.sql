-- Source match: how directly the excerpts found for a claim address its specific point, rated by the same model call
-- that writes the sources summary. Relevance only, never agreement: a source giving a different figure for the same
-- thing is 'high'. Null until the summary step has run.
alter table public.claims add column if not exists sources_match text check (sources_match in ('high', 'medium', 'low'));
grant select (sources_match) on public.claims to anon, authenticated;
