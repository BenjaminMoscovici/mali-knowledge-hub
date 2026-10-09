-- Add only the two reviewed PADEL finding categories to the existing guard.
-- No facts, active release pointers, privileges or RLS policies are changed.
begin;
set local lock_timeout = '3s';
set local statement_timeout = '30s';
set local search_path = public, pg_catalog;
lock table public.mkh_source_records in access exclusive mode;
do $guard$
begin
 if (select md5(pg_get_constraintdef(oid)) from pg_constraint
     where conrelid = 'public.mkh_source_records'::regclass
       and conname = 'mkh_learning_semantics') is distinct from
       'e60c5faeda6c45e621ba3cb8ad4bd28c' then
  raise exception 'Learning constraint changed; reconcile before migration';
 end if;
end $guard$;
alter table public.mkh_source_records drop constraint mkh_learning_semantics;
alter table public.mkh_source_records add constraint mkh_learning_semantics check
 (source_type <> 'evaluation_finding' or
  ((payload->>'project_id' ~ '^P[0-9]{6}$'
    and payload->>'finding_kind' in
        ('results','constraints','recommendations','reported_reach','methodology_limits')
    and (payload->>'page')::integer > 0 and payload->>'finding' is not null
    and payload->>'methodology' is not null and payload->>'transferability' is not null) is true));
commit;
