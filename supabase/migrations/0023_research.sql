-- How an answer's sources were researched: the checkable points, what independent pages say about each (with a
-- verified quote), and where the sources came from. claims.research is written by the lookup (agents/research.py);
-- claim_sources.independence says whether a page is independent of the speaker.
--   claims.research = {"points": [{"text", "kind", "status", "findings": [{"url", "site", "title", "independence",
--                      "relation", "finding", "quote", "position"}]}], "positions": [...], "queries": [...], "dropped": {...}}
alter table public.claims add column if not exists research jsonb;
alter table public.claim_sources add column if not exists independence text
  check (independence in ('independent', 'own_organisation', 'same_episode'));

grant select (research) on public.claims to anon, authenticated;
