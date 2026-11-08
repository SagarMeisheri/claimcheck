-- The analysis steps of a video, kept after the run: [{"key", "label", "status": done | skipped, "detail"}].
-- While a video is analysed they are also in episodes.progress (which is cleared when the run ends); this copy stays,
-- so the video page can list what was done in a "Steps" tab.
alter table public.episodes add column if not exists steps jsonb;
grant select (steps) on public.episodes to anon, authenticated;
