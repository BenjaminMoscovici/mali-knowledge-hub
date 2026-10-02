-- GIZ MKH only. Transactional extension; existing data/checks/RLS/grants retained.
begin;
set local search_path=public,pg_catalog;
alter table public.mkh_source_records drop constraint mkh_source_records_source_type_check;
alter table public.mkh_source_records add constraint mkh_source_records_source_type_check
 check(source_type in ('operational_presence','displacement_stock','food_security_classification','funding_aggregate',
 'development_project','aid_activity','evaluation_finding','eu_programming','eu_tei','eu_project_metadata','eib_project','echo_programming','eu_activity'));
alter table public.mkh_source_records add constraint mkh_eu_stage_semantics check
 (source_type not in ('eu_programming','eu_tei','eu_project_metadata','eib_project','echo_programming','eu_activity') or
 ((payload->>'title' is not null and jsonb_typeof(payload->'facts')='object'
 and payload->>'evidence_stage' in ('strategy_programming_intent','financing_commitment','implementation_status_reported','financing_signature','activity_registry_status')
 and payload->>'limitations' is not null and payload->'geography'->>'country'='Mali') is true));
alter table public.mkh_source_records add constraint mkh_eu_activity_scope check
 (source_type <> 'eu_activity' or
 ((payload->'facts'->>'publisher_ref' in ('XI-IATI-EC_INTPA','XI-IATI-EC_ECHO')
 and payload->'facts'->>'activity_id' like (payload->'facts'->>'publisher_ref')||'-%'
 and (payload->'facts'->>'country_percent_reported')::numeric=100
 and (payload->'facts'->>'source_sector_rows')::integer>0
 and payload->'facts'->>'financial_unit_status' is not null) is true));
commit;
