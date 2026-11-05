-- Q&A view of a video: questions a reader would ask, each pointing at the stored statements that answer it.
-- qa: [{"q": "Is NPCI a regulator?", "claim_ids": ["<claims.id>", ...]}] in the order the answers come in the video.
-- Only ids are stored: the page reads the statements and their sources from `claims`, so the answer text is never a copy.
alter table public.episodes add column if not exists qa jsonb;
alter table public.episodes add column if not exists qa_generated_at timestamptz;

grant select (qa, qa_generated_at) on public.episodes to anon, authenticated;
