-- Explicit privileges for the API roles. Newer Supabase projects/CLI versions no longer grant
-- these automatically on tables created in migrations. RLS (0001) still decides which rows anon can see.

grant usage on schema public to anon, authenticated, service_role;

-- Writes and internal reads: server-side only (pipeline + web server actions).
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;

-- Public read of published content. channels and episodes already have column-level grants (0001/0003).
grant select on public.claims, public.verdicts, public.citations to anon, authenticated;
