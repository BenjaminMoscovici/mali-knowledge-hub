-- Read-only V3 migration verification for the GIZ project.
-- Run this BEFORE retrying 001_admin_ingestion.sql after an uncertain SQL Editor response.
-- It returns object metadata and counts, never corpus content or credentials.

select
  to_regclass('public.ingestion_jobs') is not null as job_table_exists,
  coalesce((select c.relrowsecurity from pg_class c
            where c.oid = to_regclass('public.ingestion_jobs')), false)
    as job_rls_enabled,
  case when to_regclass('public.ingestion_jobs') is null then null
       else has_table_privilege('anon', 'public.ingestion_jobs', 'SELECT')
  end as anon_can_read_jobs,
  case when to_regclass('public.ingestion_jobs') is null then null
       else has_table_privilege('authenticated', 'public.ingestion_jobs', 'SELECT')
  end as authenticated_can_read_jobs,
  to_regprocedure('public.publish_ingestion(uuid,jsonb,jsonb,jsonb)') is not null
    as publish_rpc_exists,
  case when to_regprocedure('public.publish_ingestion(uuid,jsonb,jsonb,jsonb)') is null
       then null
       else has_function_privilege('anon',
            'public.publish_ingestion(uuid,jsonb,jsonb,jsonb)', 'EXECUTE')
  end as anon_can_execute_publish,
  case when to_regprocedure('public.publish_ingestion(uuid,jsonb,jsonb,jsonb)') is null
       then null
       else has_function_privilege('authenticated',
            'public.publish_ingestion(uuid,jsonb,jsonb,jsonb)', 'EXECUTE')
  end as authenticated_can_execute_publish,
  case when to_regprocedure('public.publish_ingestion(uuid,jsonb,jsonb,jsonb)') is null
       then null
       else has_function_privilege('service_role',
            'public.publish_ingestion(uuid,jsonb,jsonb,jsonb)', 'EXECUTE')
  end as service_role_can_execute_publish,
  (select b.public from storage.buckets b where b.id = 'mkh-originals')
    as originals_bucket_public,
  (select format_type(a.atttypid, a.atttypmod) from pg_attribute a
    where a.attrelid = to_regclass('public.chunks')
      and a.attname = 'embedding' and not a.attisdropped)
    as chunk_embedding_type,
  (select count(*) from public.documents) as document_count,
  (select count(*) from public.chunks) as chunk_count;
