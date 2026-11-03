-- What the sources found for a claim say, in 1-2 sentences citing them as [1], [2], written by a cheap model from the
-- search results' page text. A description only: nothing says whether the claim is right (checked in code for judging
-- words; a summary that fails the check is left empty and the sources are shown without it).
alter table public.claims add column if not exists sources_summary text;
grant select (sources_summary) on public.claims to anon, authenticated;
