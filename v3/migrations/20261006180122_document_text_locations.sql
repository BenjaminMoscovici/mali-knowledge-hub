-- Add text-format provenance without inventing printed page numbers.
-- Existing PDF rows, retrieval, RLS, and service-role-only publishing retained.
-- The originals bucket stays PRIVATE; no grants or policies are expanded.
alter table public.chunks alter column page_number drop not null;
update storage.buckets set allowed_mime_types = array[
  'application/pdf', 'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.oasis.opendocument.text', 'application/rtf',
  'text/plain', 'text/markdown', 'text/csv', 'text/tab-separated-values'
]::text[] where id = 'mkh-originals' and public = false;

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
    if nullif(trim(v_chunk->>'content'), '') is null
       or coalesce(jsonb_typeof(v_chunk->'embedding') <> 'array', true)
       or coalesce(jsonb_array_length(v_chunk->'embedding') <> 1536, true)
       or coalesce((v_chunk->>'chunk_index')::integer <> v_count, true) then
      raise exception 'Chunk validation failed';
    end if;
    if nullif(v_chunk->>'page_number', '') is null then
      if coalesce(p_quality->>'format', '') not in ('doc', 'docx', 'odt', 'rtf', 'txt', 'md', 'csv', 'tsv')
         or coalesce(p_quality->>'locator_type', '') <> 'original_text_location'
         or coalesce((p_quality->>'pages')::integer, -1) <> 0
         or nullif(trim(v_chunk->>'section_title'), '') is null then
        raise exception 'Original text location required for non-PDF chunks';
      end if;
    elsif (v_chunk->>'page_number')::integer < 1
       or (v_chunk->>'page_number')::integer > coalesce((p_quality->>'pages')::integer, 0)
       or coalesce((p_quality->>'pages')::integer, 0) < 1 then
      raise exception 'PDF page provenance validation failed';
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
