-- "Sources summary": 1-2 plain sentences summarising the excerpts shown under a claim's sources, written by a cheap
-- model from those excerpts only. A description only: nothing says whether the claim is right (checked in code for
-- judging words; a summary that fails the check is left empty and the sources are shown without it).
alter table public.claims add column if not exists sources_summary text;
grant select (sources_summary) on public.claims to anon, authenticated;
