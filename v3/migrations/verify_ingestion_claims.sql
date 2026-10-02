-- Read-only checks after 002_ingestion_claims.sql. All rows should be true.
select
  to_regclass('public.ingestion_jobs_live_sha256_idx') is not null as unique_index_exists,
  to_regprocedure('public.claim_ingestion_job(uuid)') is not null as claim_function_exists,
  not has_function_privilege('anon', 'public.claim_ingestion_job(uuid)', 'EXECUTE') as anon_blocked,
  not has_function_privilege('authenticated', 'public.claim_ingestion_job(uuid)', 'EXECUTE') as authenticated_blocked,
  has_function_privilege('service_role', 'public.claim_ingestion_job(uuid)', 'EXECUTE') as service_role_allowed;

-- This should return no rows. Resolve any duplicates before applying the index.
select sha256, count(*) as live_jobs
from public.ingestion_jobs
where status in ('uploaded', 'queued', 'processing', 'ready')
group by sha256
having count(*) > 1;
