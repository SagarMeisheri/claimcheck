-- A source lookup saves what it has found as it goes (the tags, the points, the queries, the pages, the verdict). Realtime sends each
-- update of a claim to the video page, so an answer's card fills in while the lookup runs. The page reads claims with the anon key,
-- so row level security (claims_public_read) decides which updates a visitor is sent. If Realtime is not running the page polls instead.
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'claims') then
    alter publication supabase_realtime add table public.claims;
  end if;
end $$;
