-- GIZ MKH hofoubbmepacdljeablj only. Extends private additive source table.
-- Existing operational/displacement semantics, RLS and privileges preserved.
begin;
set local search_path=public,pg_catalog;
alter table public.mkh_source_records drop constraint mkh_source_records_source_type_check;
alter table public.mkh_source_records add constraint mkh_source_records_source_type_check
 check (source_type in ('operational_presence','displacement_stock','food_security_classification','funding_aggregate'));
alter table public.mkh_source_records add constraint mkh_ch_semantics check
 (source_type <> 'food_security_classification' or
  ((payload->>'methodology'='Cadre Harmonise' and payload->>'period_type' in ('current','projected')
   and payload->>'unit'='people_estimated' and (payload->>'population')::numeric >= 0
   and (payload->>'phase35')::numeric >= 0 and jsonb_typeof(payload->'phase_populations')='object') is true));
alter table public.mkh_source_records add constraint mkh_funding_semantics check
 (source_type <> 'funding_aggregate' or
  ((payload->>'currency'='USD' and payload->>'country'='Mali' and payload->>'funding_definition' is not null
   and (payload->>'year')::integer >= 2000
   and (payload->>'requirements' is null or (payload->>'requirements')::numeric >= 0)
   and (payload->>'funding' is null or (payload->>'funding')::numeric >= 0)) is true));
commit;
