-- Additive V3 migration. Apply in the GIZ Supabase project after schema review.
-- Existing V1/V2 documents, chunks, indexes and match_chunks remain unchanged.

create table if not exists public.ingestion_jobs (
  id uuid primary key default gen_random_uuid(),
  filename text not null,
  original_path text not null unique,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  byte_count bigint not null check (byte_count >= 0),
  uploaded_by text not null,
  uploaded_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  status text not null check (status in
    ('uploaded', 'queued', 'processing', 'ready', 'partially processed', 'failed')),
  error text,
  quality jsonb not null default '{}'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  document_id uuid references public.documents(id)
);

create index if not exists ingestion_jobs_uploaded_at_idx
  on public.ingestion_jobs (uploaded_at desc);
create index if not exists ingestion_jobs_status_idx
  on public.ingestion_jobs (status, uploaded_at desc);
create or replace function public.touch_ingestion_job() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;
drop trigger if exists ingestion_jobs_updated on public.ingestion_jobs;
create trigger ingestion_jobs_updated before update on public.ingestion_jobs
for each row execute function public.touch_ingestion_job();
alter table public.ingestion_jobs enable row level security;
revoke all on public.ingestion_jobs from anon, authenticated;

-- Originals must never be served by a public URL. The server's secret key is
-- the only route to the bucket; no user-facing storage policy is installed.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('mkh-originals', 'mkh-originals', false, 20971520,
        array['application/pdf']::text[])
on conflict (id) do nothing;

-- The application prepares every embedding before calling this RPC. The RPC
-- publishes a complete, validated document and its chunks atomically.
create or replace function public.publish_ingestion(
  p_job_id uuid, p_metadata jsonb, p_quality jsonb, p_chunks jsonb
) returns uuid
language plpgsql security definer set search_path = public, extensions
as $$
declare
  v_job public.ingestion_jobs%rowtype;
  v_doc_id uuid;
  v_chunk jsonb;
  v_count integer := 0;
begin
  select * into v_job from public.ingestion_jobs where id = p_job_id for update;
  if not found or v_job.status <> 'processing' then
    raise exception 'Job must exist and be processing';
  end if;
  if jsonb_typeof(p_chunks) <> 'array'
     or jsonb_array_length(p_chunks) < 1
     or jsonb_array_length(p_chunks) > 2000
     or (p_quality->>'chunks')::integer <> jsonb_array_length(p_chunks)
     or (p_quality->>'embeddings')::integer <> jsonb_array_length(p_chunks)
     or nullif(p_metadata->>'title', '') is null then
    raise exception 'Document validation failed';
  end if;

  if v_job.document_id is null then
    insert into public.documents
      (title, organization, publication_date, document_type, language,
       geographic_scope, version, status)
    values
      (p_metadata->>'title', p_metadata->>'organization',
       nullif(p_metadata->>'publication_date', '')::date,
       p_metadata->>'document_type', p_metadata->>'language',
       p_metadata->>'geographic_scope', p_metadata->>'version', 'active')
    returning id into v_doc_id;
  else
    v_doc_id := v_job.document_id;
    update public.documents set
      title = p_metadata->>'title',
      organization = p_metadata->>'organization',
      publication_date = nullif(p_metadata->>'publication_date', '')::date,
      document_type = p_metadata->>'document_type',
      language = p_metadata->>'language',
      geographic_scope = p_metadata->>'geographic_scope',
      version = p_metadata->>'version'
    where id = v_doc_id;
    if not found then raise exception 'Previous document missing'; end if;
    delete from public.chunks where document_id = v_doc_id;
  end if;

  for v_chunk in select value from jsonb_array_elements(p_chunks) loop
    if (v_chunk->>'page_number')::integer < 1
       or (v_chunk->>'page_number')::integer > (p_quality->>'pages')::integer
       or nullif(v_chunk->>'content', '') is null
       or jsonb_array_length(v_chunk->'embedding') <> 1536 then
      raise exception 'Chunk validation failed';
    end if;
    insert into public.chunks
      (document_id, page_number, chunk_index, section_title, content, embedding)
    values
      (v_doc_id, (v_chunk->>'page_number')::integer,
       (v_chunk->>'chunk_index')::integer, v_chunk->>'section_title',
       v_chunk->>'content', (v_chunk->>'embedding')::vector(1536));
    v_count := v_count + 1;
  end loop;

  update public.ingestion_jobs set
    status = 'ready', error = null, quality = p_quality, metadata = p_metadata,
    document_id = v_doc_id, updated_at = now()
  where id = p_job_id;
  return v_doc_id;
end;
$$;

revoke all on function public.publish_ingestion(uuid, jsonb, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.publish_ingestion(uuid, jsonb, jsonb, jsonb)
  to service_role;
