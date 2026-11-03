-- Three statement types for podcasts: advice (a recommendation to the listener), story (a personal experience) and
-- question (a substantive question, usually from the host). Questions and stories assert nothing a source could
-- address, so they never get "Check sources" (sources_status stays 'not_eligible'). Existing rows keep their tags.
alter table public.claims drop constraint if exists claims_statement_type_check;
alter table public.claims add constraint claims_statement_type_check
  check (statement_type in ('factual_claim', 'opinion', 'forecast', 'advice', 'story', 'question', 'other'));
