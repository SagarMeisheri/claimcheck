-- Each extracted item is now an answer to a question: the question, who asked it and whether it was asked or inferred
-- from an unprompted passage are saved with the answer (claims.claim_text is the answer, claims.speaker who gave it).
-- Rows from earlier videos have no question and keep working.
alter table public.claims add column if not exists question text;
alter table public.claims add column if not exists asked_by text;
alter table public.claims add column if not exists question_kind text check (question_kind in ('asked', 'implied'));

grant select (question, asked_by, question_kind) on public.claims to anon, authenticated;
