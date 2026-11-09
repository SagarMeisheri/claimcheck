-- Where the question starts in the video (agents/stages.py, from the extractor's question_ts). claims.start_s is where the ANSWER starts, so playing a
-- card from start_s dropped the viewer into the middle of the exchange. The page plays from question_start_s (the asker's first word) and shows
-- that time on the card. Null for videos read before this existed, for implied questions and for times that were not believable: the page then
-- estimates the start from the length of the question as spoken.
alter table public.claims add column if not exists question_start_s integer;

grant select (question_start_s) on public.claims to anon, authenticated;
