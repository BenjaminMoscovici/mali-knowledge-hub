-- V3 follow-up: one active attempt per job and one live job per original.
-- Apply after 001_admin_ingestion.sql. No V1/V2 objects are changed.

create unique index if not exists ingestion_jobs_live_sha256_idx
  on public.ingestion_jobs (sha256)
  where status in ('uploaded', 'queued', 'processing', 'ready');

create or replace function public.claim_ingestion_job(p_job_id uuid)
returns public.ingestion_jobs
language plpgsql security definer set search_path = ''
as $$
declare
  v_job public.ingestion_jobs%rowtype;
begin
  update public.ingestion_jobs
     set status = 'processing', error = null
   where id = p_job_id
     and status in ('queued', 'failed', 'partially processed', 'ready')
  returning * into v_job;
  if not found then
    raise exception 'Job is already processing or cannot be processed'
      using errcode = 'P0001';
  end if;
  return v_job;
end;
$$;

revoke all on function public.claim_ingestion_job(uuid)
  from public, anon, authenticated;
grant execute on function public.claim_ingestion_job(uuid) to service_role;
