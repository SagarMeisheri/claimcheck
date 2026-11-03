-- "Check sources" works for every statement type (claim, opinion, forecast, other), not just claims.
-- Only statements redacted by the content policy (not_checked_reason = 'outside_policy') stay not_eligible.

-- Older pipelines marked every non-claim policy_tier 'never' with its type as the reason ('opinion', 'forecast',
-- 'hearsay', ...). Those statements are shown publicly; the marker only meant "no sources". Clear it.
update public.claims
   set policy_tier = 'normal', not_checked_reason = null
 where policy_tier = 'never'
   and not_checked_reason is distinct from 'outside_policy';

update public.claims
   set not_checked_reason = null
 where not_checked_reason is not null
   and not_checked_reason <> 'outside_policy';

update public.claims
   set sources_status = 'not_requested'
 where sources_status = 'not_eligible'
   and not_checked_reason is distinct from 'outside_policy';
