-- GIZ MKH only. Append-only facts; existing source checks and security retained.
begin;
set local search_path=public,pg_catalog;
alter table public.mkh_source_records drop constraint mkh_source_records_source_type_check;
alter table public.mkh_source_records add constraint mkh_source_records_source_type_check
 check (source_type in ('operational_presence','displacement_stock','food_security_classification','funding_aggregate',
                       'development_project','aid_activity','evaluation_finding'));
alter table public.mkh_source_records add constraint mkh_project_semantics check
 (source_type <> 'development_project' or
  ((payload->>'country'='Mali' and payload->>'project_id' ~ '^P[0-9]{6}$'
   and payload->>'status' in ('Active','Pipeline','Closed','Dropped')
   and payload->>'title' is not null and payload->>'financial_unit_status' is not null) is true));
alter table public.mkh_source_records add constraint mkh_aid_semantics check
 (source_type <> 'aid_activity' or
  ((payload->>'country'='Mali' and payload->>'publisher_ref'='44000'
   and payload->>'activity_id' ~ '^44000-P[0-9]{6}$'
   and payload->>'project_id' ~ '^P[0-9]{6}$' and jsonb_typeof(payload->'sectors')='array'
   and (payload->>'source_sector_rows')::integer > 0 and payload->>'financial_unit_status' is not null) is true));
alter table public.mkh_source_records add constraint mkh_learning_semantics check
 (source_type <> 'evaluation_finding' or
  ((payload->>'project_id' ~ '^P[0-9]{6}$' and payload->>'finding_kind' in ('results','constraints','recommendations')
   and (payload->>'page')::integer > 0 and payload->>'finding' is not null
   and payload->>'methodology' is not null and payload->>'transferability' is not null) is true));
commit;
