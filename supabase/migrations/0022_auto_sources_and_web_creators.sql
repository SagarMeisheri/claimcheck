-- Videos whose sources are looked up automatically: the page then shows progress instead of a "Check sources" button.
alter table public.episodes add column if not exists auto_sources boolean;
grant select (auto_sources) on public.episodes to anon, authenticated;

-- Creators found by a web search for channels that aren't on the curated top-100 list (agents/creators.py).
-- They have no rank; `source` tells them apart. profile.identified = false remembers a channel the search couldn't
-- describe, so it isn't searched again.
alter table public.creators alter column rank drop not null;
alter table public.creators add column if not exists source text not null default 'curated' check (source in ('curated', 'web_search'));
