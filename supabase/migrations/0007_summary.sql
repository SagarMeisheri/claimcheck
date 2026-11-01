-- One short, neutral summary of each video, written by the extractor from the statements it found.
alter table public.episodes add column if not exists summary text;
grant select (summary) on public.episodes to anon, authenticated;
