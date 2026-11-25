create table public.mkh_v3_editors (
    user_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.mkh_v3_editors enable row level security;
revoke all on public.mkh_v3_editors from public, anon, authenticated;
grant select on public.mkh_v3_editors to authenticated;
create policy mkh_v3_see_own_editor_role on public.mkh_v3_editors for select to authenticated
    using (user_id = (select auth.uid()));

create table public.mkh_v3_source_versions (
    id uuid primary key default gen_random_uuid(),
    source_id text not null check (source_id ~ '^[a-z][a-z0-9-]{0,89}$'),
    release text not null check (length(release) between 1 and 140),
    manifest jsonb not null check (jsonb_typeof(manifest) = 'object' and octet_length(manifest::text) <= 1500000),
    created_at timestamptz not null default now(),
    unique (source_id, id), unique (source_id, release),
    check (manifest->>'id' is not distinct from source_id and manifest->>'release' is not distinct from release)
);
create table public.mkh_v3_publications (
    source_id text primary key check (source_id ~ '^[a-z][a-z0-9-]{0,89}$'),
    status text not null check (status in ('published','suspended','withdrawn','bundled')),
    version_id uuid,
    revision uuid not null default gen_random_uuid(),
    foreign key (source_id, version_id) references public.mkh_v3_source_versions(source_id, id),
    check ((status = 'published') = (version_id is not null))
);
alter table public.mkh_v3_source_versions enable row level security;
alter table public.mkh_v3_publications enable row level security;
revoke all on public.mkh_v3_source_versions, public.mkh_v3_publications from public, anon, authenticated;
grant select on public.mkh_v3_source_versions, public.mkh_v3_publications to anon, authenticated;
grant insert (source_id,release,manifest) on public.mkh_v3_source_versions to authenticated;
grant insert (source_id,status,version_id,revision), update (status,version_id,revision)
    on public.mkh_v3_publications to authenticated;
create policy mkh_v3_active_source_version on public.mkh_v3_source_versions for select to anon, authenticated using
    (exists (select from public.mkh_v3_publications p where p.source_id=mkh_v3_source_versions.source_id
             and p.version_id=mkh_v3_source_versions.id and p.status='published'));
create policy mkh_v3_editor_versions on public.mkh_v3_source_versions for all to authenticated
    using (exists (select 1 from public.mkh_v3_editors e where e.user_id = (select auth.uid())))
    with check (exists (select 1 from public.mkh_v3_editors e where e.user_id = (select auth.uid())));
create policy mkh_v3_publication_read on public.mkh_v3_publications for select to anon, authenticated using (true);
create policy mkh_v3_editor_publish on public.mkh_v3_publications for all to authenticated
    using (exists (select 1 from public.mkh_v3_editors e where e.user_id = (select auth.uid())))
    with check (exists (select 1 from public.mkh_v3_editors e where e.user_id = (select auth.uid())));
