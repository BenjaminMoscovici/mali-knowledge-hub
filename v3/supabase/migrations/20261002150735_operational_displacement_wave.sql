-- Authorized target: GIZ MKH hofoubbmepacdljeablj. Additive; no existing rows/tables changed.
-- Immutable aggregates and semantic payloads; service-role-only, no public access.
begin;
set local search_path=public,pg_catalog;
create table public.mkh_source_records (
 id uuid primary key,
 release_id uuid not null references public.mkh_source_releases(id),
 span_id uuid not null,
 source_type text not null check (source_type in ('operational_presence','displacement_stock')),
 reference_start date not null,
 reference_end date not null check (reference_end >= reference_start),
 payload jsonb not null check (jsonb_typeof(payload)='object'),
 foreign key(release_id,span_id) references public.mkh_evidence_spans(release_id,id),
 constraint mkh_presence_semantics check (source_type <> 'operational_presence' or
   ((payload->>'activity_status'='presence_only' and payload->>'organization' is not null
    and payload->>'sector' is not null
    and payload->>'reached' is null and payload->>'targeted' is null
    and payload->>'activity' is null and payload->>'start_date' is null and payload->>'end_date' is null) is true)),
 constraint mkh_displacement_semantics check (source_type <> 'displacement_stock' or
   ((payload->>'measure'='stock' and payload->>'category' in ('internally_displaced','returned_idps','repatriated_persons')
    and payload->>'unit'='people' and (payload->>'value')::bigint >= 0) is true))
);
create index mkh_source_records_release on public.mkh_source_records(release_id,source_type);
create index mkh_source_records_geography on public.mkh_source_records((payload->'geography'->>'region'),(payload->'geography'->>'cercle'));
alter table public.mkh_source_records enable row level security;
revoke all on public.mkh_source_records from public,anon,authenticated,service_role;
grant select,insert on public.mkh_source_records to service_role;
commit;
