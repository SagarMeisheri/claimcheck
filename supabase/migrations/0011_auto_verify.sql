-- Automatic whole-video verification.
-- verdicts.basis: 'sources' (cited quotes) or 'model_knowledge' (answered from general knowledge, no source searched).
-- episodes.auto_verify_status: 'running' while the automatic verifier works through a video's claims, then 'done'.
alter table public.verdicts add column if not exists basis text not null default 'sources' check (basis in ('sources', 'model_knowledge'));
alter table public.episodes add column if not exists auto_verify_status text;
grant select (auto_verify_status) on public.episodes to anon, authenticated;
