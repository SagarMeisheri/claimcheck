-- Verdict score and correction.
-- score: 0-100 truthfulness computed in code from the checked verdict, the judge's confidence and the sources
--        (100 = clearly supported, 0 = clearly contradicted). Null when the claim is unverifiable.
-- correction: for False verdicts, the correct fact according to the cited sources.
alter table public.verdicts add column if not exists score smallint check (score between 0 and 100);
alter table public.verdicts add column if not exists correction text;

-- Channels are also created automatically when someone submits a video from a channel we don't track
-- (id and name come from the video's own metadata). polled = false keeps the RSS cron from polling them,
-- so it only keeps polling the curated launch channels.
alter table public.channels add column if not exists polled boolean not null default true;
