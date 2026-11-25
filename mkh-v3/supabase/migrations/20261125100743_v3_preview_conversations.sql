create table public.mkh_v3_conversations (
    id uuid primary key,
    owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
    title text not null check (char_length(title) between 1 and 120),
    turns jsonb not null default '[]'::jsonb
        check (jsonb_typeof(turns) = 'array' and octet_length(turns::text) <= 786432),
    revision integer not null default 0 check (revision >= 0),
    updated_at timestamptz not null default now()
);

alter table public.mkh_v3_conversations enable row level security;
revoke all on public.mkh_v3_conversations from public, anon, authenticated;
grant select, delete on public.mkh_v3_conversations to authenticated;
grant insert (id, title, turns, revision, updated_at), update (turns, revision, updated_at)
    on public.mkh_v3_conversations to authenticated;

create policy mkh_v3_owner_conversations on public.mkh_v3_conversations
    for all to authenticated
    using ((select auth.uid()) = owner_id)
    with check ((select auth.uid()) = owner_id);

create index mkh_v3_recent_conversations
    on public.mkh_v3_conversations (owner_id, updated_at desc);

create table public.mkh_v3_attempts (
    id uuid primary key,
    owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
    attempted_at timestamptz not null default now()
);

alter table public.mkh_v3_attempts enable row level security;
revoke all on public.mkh_v3_attempts from public, anon, authenticated;
grant select, insert (id) on public.mkh_v3_attempts to authenticated;

create policy mkh_v3_owner_attempts_read on public.mkh_v3_attempts
    for select to authenticated using ((select auth.uid()) = owner_id);

create policy mkh_v3_owner_attempts_create on public.mkh_v3_attempts
    for insert to authenticated with check ((select auth.uid()) = owner_id);

create index mkh_v3_recent_attempts
    on public.mkh_v3_attempts (owner_id, attempted_at desc);
