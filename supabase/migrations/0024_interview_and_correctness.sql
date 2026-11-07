-- How each question was asked (agents/tags.py, one of the answer tags), saved on the answer it was asked for:
--   claims.question_analysis = {"type": "open"|"closed"|"leading"|"softball"|"challenging"|"unclear",
--                               "p": the classifier's probability for the type,
--                               "spoken": true if it was tagged from the host's own words, false if from the AI's plain-words version}
-- The page tallies these into an interview profile. The other answer tags (support, match, bias, stake) and the pages they rest on are
-- stored inside claims.research (research.tags, research.correctness), so they need no column.
alter table public.claims add column if not exists question_analysis jsonb;

grant select (question_analysis) on public.claims to anon, authenticated;

-- The question as the asker said it (framing, praise or a view voiced before the question). claims.question is the extractor's
-- plain-words rewrite and leaves that out, so how a question was put is judged from this one.
alter table public.claims add column if not exists question_quote text;

grant select (question_quote) on public.claims to anon, authenticated;
