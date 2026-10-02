-- Applied to authorized GIZ MKH project on 2 October 2026 after namespace/schema audit.
-- Correct target only: GIZ MKH hofoubbmepacdljeablj. Existing data and RLS preserved.
-- Additive source stage; existing tables/functions and public UI are untouched.
-- Fail on namespace collisions; do not disguise an unknown schema with IF NOT EXISTS.

begin;
set local search_path=public,pg_catalog;

create table mkh_sources (
 id text primary key, provider text not null, title text not null, url text not null);
create table mkh_datasets (
 id text primary key, source_id text not null references mkh_sources(id),
 title text not null, refresh_policy text not null, current_release_id uuid);
create table mkh_ingestion_runs (
 id uuid primary key, dataset_id text not null, started_at timestamptz not null,
 finished_at timestamptz, status text not null, release_id uuid, error_class text);
create table mkh_source_releases (
 id uuid primary key, dataset_id text not null references mkh_datasets(id),
 checksum text not null, upstream_version text not null, retrieved_at timestamptz not null,
 publication_date date, reference_start date, reference_end date,
 source_url text not null, original_file text not null, license text not null,
 license_url text not null, attribution text not null, access text not null,
 transformation text not null, quality_json jsonb not null,
 run_id uuid not null references mkh_ingestion_runs(id), status text not null);
create table mkh_geo_units (
 id uuid primary key, release_id uuid not null references mkh_source_releases(id),
 parent_id uuid references mkh_geo_units(id), level text not null,
 name text not null, unit_type text not null, boundary_version text not null, valid_on date,
 valid_to date, geometry_json jsonb, original_record_id text not null,
 unique(release_id,original_record_id));
create table mkh_geo_names (
 id uuid primary key, unit_id uuid not null references mkh_geo_units(id),
 name text not null, folded_name text not null, language text, kind text not null);
create table mkh_geo_identifiers (
 id uuid primary key, unit_id uuid not null references mkh_geo_units(id),
 namespace text not null, identifier text not null,
 unique(unit_id,namespace,identifier));
create table mkh_evidence_spans (
 id uuid primary key, release_id uuid not null references mkh_source_releases(id),
 original_record_id text not null, page integer, printed_page text,
 section text, passage text not null, locator text not null);
create table mkh_population_observations (
 id uuid primary key, release_id uuid not null references mkh_source_releases(id),
 unit_id uuid not null references mkh_geo_units(id),
 span_id uuid not null references mkh_evidence_spans(id),
 sex text not null, value integer not null, unit text not null,
 reference_start date not null, reference_end date not null,
 methodology text not null, geographic_precision text not null,
 unique(release_id,unit_id,sex));
create table mkh_humanitarian_observations (
 id uuid primary key, release_id uuid not null references mkh_source_releases(id),
 unit_id uuid not null references mkh_geo_units(id),
 span_id uuid not null references mkh_evidence_spans(id),
 sector text not null, category text not null, population_status text not null,
 value integer not null, unit text not null, reference_start date not null,
 reference_end date not null, methodology text not null,
 geographic_precision text not null,
 unique(release_id,unit_id,sector,category,population_status));
create table mkh_document_pages (
 release_id uuid not null references mkh_source_releases(id), page integer not null,
 content text not null, primary key(release_id,page));
create table mkh_geo_crosswalks (
 id uuid primary key, from_unit_id uuid not null references mkh_geo_units(id),
 to_unit_id uuid not null references mkh_geo_units(id), relation text not null,
 method text not null, confidence double precision not null, status text not null,
 supersedes uuid references mkh_geo_crosswalks(id), rationale text not null,
 recorded_at timestamptz not null);
create table mkh_geo_unresolved (
 id uuid primary key, release_id uuid not null references mkh_source_releases(id),
 unit_id uuid not null references mkh_geo_units(id),
 raw_name text not null, level text not null, parent_name text,
 candidates_json jsonb not null, reason text not null, status text not null);
create index mkh_geo_lookup on mkh_geo_names(folded_name,unit_id);
create index mkh_geo_parent on mkh_geo_units(parent_id);
create index mkh_population_geo on mkh_population_observations(unit_id,sex);

alter table public.mkh_source_releases add constraint mkh_release_hash check (checksum ~ '^[0-9a-f]{64}$');
alter table public.mkh_source_releases add constraint mkh_release_access check (access = 'public_aggregate');
alter table public.mkh_source_releases add constraint mkh_release_status check (status in ('validated','validated_with_limitations'));
alter table public.mkh_source_releases add constraint mkh_release_dates check (reference_end >= reference_start);
alter table public.mkh_source_releases add unique(dataset_id,id);
alter table public.mkh_datasets add constraint mkh_current_release_fk foreign key(id,current_release_id)
  references public.mkh_source_releases(dataset_id,id) deferrable initially deferred;
alter table public.mkh_geo_units add constraint mkh_geo_level check (level in ('country','region','cercle','commune','arrondissement','locality'));
alter table public.mkh_geo_units add constraint mkh_geo_type check ((level='region' and unit_type in ('region','district')) or (level<>'region' and unit_type=level));
alter table public.mkh_geo_units add constraint mkh_geo_dates check (valid_to >= valid_on);
alter table public.mkh_geo_units add constraint mkh_geo_root check ((level='country') = (parent_id is null));
alter table public.mkh_geo_units add unique(release_id,id);
alter table public.mkh_geo_units add constraint mkh_geo_same_release_parent foreign key(release_id,parent_id)
  references public.mkh_geo_units(release_id,id) deferrable initially deferred;
alter table public.mkh_evidence_spans add unique(release_id,id);
alter table public.mkh_evidence_spans add constraint mkh_span_page check (page is null or page > 0);
alter table public.mkh_document_pages add constraint mkh_document_page_positive check (page > 0);
alter table public.mkh_population_observations add constraint mkh_population_sex check (sex in ('male','female','total'));
alter table public.mkh_population_observations add constraint mkh_population_value check (value >= 0 and unit='people');
alter table public.mkh_population_observations add constraint mkh_population_dates check (reference_end >= reference_start);
alter table public.mkh_population_observations add constraint mkh_population_same_release_geo foreign key(release_id,unit_id)
  references public.mkh_geo_units(release_id,id);
alter table public.mkh_population_observations add constraint mkh_population_same_release_span foreign key(release_id,span_id)
  references public.mkh_evidence_spans(release_id,id);
alter table public.mkh_humanitarian_observations add constraint mkh_humanitarian_status check (population_status in ('all','INN','TGT','AFF','REA'));
alter table public.mkh_humanitarian_observations add constraint mkh_humanitarian_value check (value >= 0 and unit='people');
alter table public.mkh_humanitarian_observations add constraint mkh_humanitarian_dates check (reference_end >= reference_start);
alter table public.mkh_humanitarian_observations add constraint mkh_humanitarian_same_release_geo foreign key(release_id,unit_id)
  references public.mkh_geo_units(release_id,id);
alter table public.mkh_humanitarian_observations add constraint mkh_humanitarian_same_release_span foreign key(release_id,span_id)
  references public.mkh_evidence_spans(release_id,id);
alter table public.mkh_geo_crosswalks add constraint mkh_crosswalk_confidence check (confidence between 0 and 1);
alter table public.mkh_geo_crosswalks add constraint mkh_crosswalk_status check (status in ('proposed','approved','rejected','revoked'));
alter table public.mkh_geo_crosswalks add constraint mkh_crosswalk_review check (status <> 'approved' or (relation <> 'candidate_identity' and length(rationale)>0));
alter table public.mkh_ingestion_runs add constraint mkh_run_status check (status in ('running','succeeded','no_op','failed'));
alter table public.mkh_sources enable row level security;
revoke all on public.mkh_sources from public, anon, authenticated, service_role;
grant select, insert on public.mkh_sources to service_role;
alter table public.mkh_datasets enable row level security;
revoke all on public.mkh_datasets from public, anon, authenticated, service_role;
grant select, insert on public.mkh_datasets to service_role;
alter table public.mkh_ingestion_runs enable row level security;
revoke all on public.mkh_ingestion_runs from public, anon, authenticated, service_role;
grant select, insert on public.mkh_ingestion_runs to service_role;
alter table public.mkh_source_releases enable row level security;
revoke all on public.mkh_source_releases from public, anon, authenticated, service_role;
grant select, insert on public.mkh_source_releases to service_role;
alter table public.mkh_geo_units enable row level security;
revoke all on public.mkh_geo_units from public, anon, authenticated, service_role;
grant select, insert on public.mkh_geo_units to service_role;
alter table public.mkh_geo_names enable row level security;
revoke all on public.mkh_geo_names from public, anon, authenticated, service_role;
grant select, insert on public.mkh_geo_names to service_role;
alter table public.mkh_geo_identifiers enable row level security;
revoke all on public.mkh_geo_identifiers from public, anon, authenticated, service_role;
grant select, insert on public.mkh_geo_identifiers to service_role;
alter table public.mkh_evidence_spans enable row level security;
revoke all on public.mkh_evidence_spans from public, anon, authenticated, service_role;
grant select, insert on public.mkh_evidence_spans to service_role;
alter table public.mkh_population_observations enable row level security;
revoke all on public.mkh_population_observations from public, anon, authenticated, service_role;
grant select, insert on public.mkh_population_observations to service_role;
alter table public.mkh_humanitarian_observations enable row level security;
revoke all on public.mkh_humanitarian_observations from public, anon, authenticated, service_role;
grant select, insert on public.mkh_humanitarian_observations to service_role;
alter table public.mkh_document_pages enable row level security;
revoke all on public.mkh_document_pages from public, anon, authenticated, service_role;
grant select, insert on public.mkh_document_pages to service_role;
alter table public.mkh_geo_crosswalks enable row level security;
revoke all on public.mkh_geo_crosswalks from public, anon, authenticated, service_role;
grant select, insert on public.mkh_geo_crosswalks to service_role;
alter table public.mkh_geo_unresolved enable row level security;
revoke all on public.mkh_geo_unresolved from public, anon, authenticated, service_role;
grant select, insert on public.mkh_geo_unresolved to service_role;
grant update on public.mkh_datasets, public.mkh_ingestion_runs to service_role;

create view public.mkh_source_freshness with (security_invoker=true) as
  select d.id,d.title,d.refresh_policy,r.id release_id,r.upstream_version,r.retrieved_at,
         r.reference_start,r.reference_end,r.status,r.quality_json
  from public.mkh_datasets d left join public.mkh_source_releases r on r.id=d.current_release_id;
revoke all on public.mkh_source_freshness from public,anon,authenticated;
grant select on public.mkh_source_freshness to service_role;

commit;
