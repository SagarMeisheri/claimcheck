-- Live progress of a check: {"label": "...", "pct": 0-100}, written by the pipeline, shown as a progress bar.
alter table public.episodes add column if not exists progress jsonb not null default '{}'::jsonb;
grant select (progress) on public.episodes to anon, authenticated;
