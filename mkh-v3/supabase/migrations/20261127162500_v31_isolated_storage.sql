create table public.mkh_v31_conversations (
    id uuid primary key,
    owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
    title text not null check (char_length(title) between 1 and 120),
    turns jsonb not null default '[]'::jsonb
        check (jsonb_typeof(turns) = 'array' and octet_length(turns::text) <= 786432),
    revision integer not null default 0 check (revision >= 0),
    updated_at timestamptz not null default now()
);

alter table public.mkh_v31_conversations enable row level security;
revoke all on public.mkh_v31_conversations from public, anon, authenticated;
grant select, delete on public.mkh_v31_conversations to authenticated;
grant insert (id, title, turns, revision, updated_at), update (turns, revision, updated_at)
    on public.mkh_v31_conversations to authenticated;

create policy mkh_v31_owner_conversations on public.mkh_v31_conversations
    for all to authenticated
    using ((select auth.uid()) = owner_id)
    with check ((select auth.uid()) = owner_id);

create index mkh_v31_recent_conversations
    on public.mkh_v31_conversations (owner_id, updated_at desc);

create table public.mkh_v31_attempts (
    id uuid primary key,
    owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
    attempted_at timestamptz not null default now()
);

alter table public.mkh_v31_attempts enable row level security;
revoke all on public.mkh_v31_attempts from public, anon, authenticated;
grant select, insert (id) on public.mkh_v31_attempts to authenticated;

create policy mkh_v31_owner_attempts_read on public.mkh_v31_attempts
    for select to authenticated using ((select auth.uid()) = owner_id);

create policy mkh_v31_owner_attempts_create on public.mkh_v31_attempts
    for insert to authenticated with check ((select auth.uid()) = owner_id);

create index mkh_v31_recent_attempts
    on public.mkh_v31_attempts (owner_id, attempted_at desc);

create table public.mkh_v31_memory (
    owner_id uuid primary key default auth.uid() references auth.users(id) on delete cascade,
    enabled boolean not null default false,
    notes text not null check (char_length(notes) between 1 and 2000)
);

alter table public.mkh_v31_memory enable row level security;
revoke all on public.mkh_v31_memory from public, anon, authenticated;
grant select, delete on public.mkh_v31_memory to authenticated;
grant insert (enabled, notes), update (enabled, notes) on public.mkh_v31_memory to authenticated;

create policy mkh_v31_own_memory on public.mkh_v31_memory for all to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);

create schema if not exists mkh_v31_private;
revoke all on schema mkh_v31_private from public, anon, authenticated;

create table public.mkh_v31_archived_turns (
    conversation_id uuid not null references public.mkh_v31_conversations(id) on delete cascade,
    ordinal integer not null check (ordinal > 0),
    owner_id uuid not null references auth.users(id) on delete cascade,
    turn jsonb not null,
    primary key (conversation_id, ordinal)
);
create index mkh_v31_archived_owner on public.mkh_v31_archived_turns(owner_id, conversation_id);
alter table public.mkh_v31_archived_turns enable row level security;
revoke all on public.mkh_v31_archived_turns from public, anon, authenticated;
grant select on public.mkh_v31_archived_turns to authenticated;
create policy mkh_v31_read_own_archive on public.mkh_v31_archived_turns for select to authenticated
    using ((select auth.uid()) = owner_id);

create function mkh_v31_private.archive_displaced_turns() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
    if new.revision = old.revision + 1 and new.owner_id = old.owner_id then
        insert into public.mkh_v31_archived_turns(conversation_id, ordinal, owner_id, turn)
        select old.id, old.revision - jsonb_array_length(old.turns) + t.n, old.owner_id, t.entry
        from jsonb_array_elements(old.turns) with ordinality as t(entry, n)
        where old.revision - jsonb_array_length(old.turns) + t.n between 1 and new.revision - jsonb_array_length(new.turns)
        on conflict do nothing;
    end if;
    return new;
end;
$$;
revoke all on function mkh_v31_private.archive_displaced_turns() from public, anon, authenticated;
create trigger mkh_v31_preserve_turns after update of turns on public.mkh_v31_conversations
    for each row execute function mkh_v31_private.archive_displaced_turns();

create function public.mkh_v31_find_archived_work(chat uuid, terms text) returns setof public.mkh_v31_archived_turns
language sql stable security invoker set search_path = '' as $$
    select a.* from public.mkh_v31_archived_turns a
    where a.conversation_id = chat and a.owner_id = (select auth.uid())
      and (btrim(terms) = '' or to_tsvector('simple', concat_ws(' ', a.turn->>'prompt', a.turn->>'answer'))
           @@ websearch_to_tsquery('simple', left(terms, 250)))
    order by a.ordinal desc limit 3
$$;
revoke all on function public.mkh_v31_find_archived_work(uuid, text) from public, anon, authenticated;
grant execute on function public.mkh_v31_find_archived_work(uuid, text) to authenticated;

create table public.mkh_v31_editors (
    user_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.mkh_v31_editors enable row level security;
revoke all on public.mkh_v31_editors from public, anon, authenticated;
grant select on public.mkh_v31_editors to authenticated;
create policy mkh_v31_see_own_editor_role on public.mkh_v31_editors for select to authenticated
    using (user_id = (select auth.uid()));

create table public.mkh_v31_source_versions (
    id uuid primary key default gen_random_uuid(),
    source_id text not null check (source_id ~ '^[a-z][a-z0-9-]{0,89}$'),
    release text not null check (length(release) between 1 and 140),
    manifest jsonb not null check (jsonb_typeof(manifest) = 'object' and octet_length(manifest::text) <= 1500000),
    created_at timestamptz not null default now(),
    unique (source_id, id), unique (source_id, release),
    check (manifest->>'id' is not distinct from source_id and manifest->>'release' is not distinct from release)
);
create table public.mkh_v31_publications (
    source_id text primary key check (source_id ~ '^[a-z][a-z0-9-]{0,89}$'),
    status text not null check (status in ('published','suspended','withdrawn','bundled')),
    version_id uuid,
    revision uuid not null default gen_random_uuid(),
    foreign key (source_id, version_id) references public.mkh_v31_source_versions(source_id, id),
    check ((status = 'published') = (version_id is not null))
);
alter table public.mkh_v31_source_versions enable row level security;
alter table public.mkh_v31_publications enable row level security;
revoke all on public.mkh_v31_source_versions, public.mkh_v31_publications from public, anon, authenticated;
grant select on public.mkh_v31_source_versions, public.mkh_v31_publications to anon, authenticated;
grant insert (source_id,release,manifest) on public.mkh_v31_source_versions to authenticated;
grant insert (source_id,status,version_id,revision), update (status,version_id,revision)
    on public.mkh_v31_publications to authenticated;
create policy mkh_v31_active_source_version on public.mkh_v31_source_versions for select to anon, authenticated using
    (exists (select from public.mkh_v31_publications p where p.source_id=mkh_v31_source_versions.source_id
             and p.version_id=mkh_v31_source_versions.id and p.status='published'));
create policy mkh_v31_editor_versions on public.mkh_v31_source_versions for all to authenticated
    using (exists (select 1 from public.mkh_v31_editors e where e.user_id = (select auth.uid())))
    with check (exists (select 1 from public.mkh_v31_editors e where e.user_id = (select auth.uid())));
create policy mkh_v31_publication_read on public.mkh_v31_publications for select to anon, authenticated using (true);
create policy mkh_v31_editor_publish on public.mkh_v31_publications for all to authenticated
    using (exists (select 1 from public.mkh_v31_editors e where e.user_id = (select auth.uid())))
    with check (exists (select 1 from public.mkh_v31_editors e where e.user_id = (select auth.uid())));

-- Research originals live outside the public Canon and application assets.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('mkh-v31-research', 'mkh-v31-research', false, 16777216, array['application/gzip']);
