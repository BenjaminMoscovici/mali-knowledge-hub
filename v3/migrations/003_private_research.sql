-- V4 user research lives separately from the shared evidence corpus.
-- Run on the GIZ Mali Knowledge Hub project; the public guest remains anonymous.

create table if not exists public.mkh_user_conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    title text not null default 'New conversation'
        check (length(title) between 1 and 120),
    analysis_mode text not null default 'balanced'
        check (analysis_mode in ('quick', 'balanced', 'deep')),
    archived_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id, user_id)
);

create index if not exists mkh_user_conversations_recent
    on public.mkh_user_conversations (user_id, updated_at desc);

create table if not exists public.mkh_user_messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null,
    user_id uuid not null default auth.uid(),
    position integer not null check (position > 0),
    role text not null check (role in ('user', 'assistant')),
    content text not null check (length(content) <= 50000),
    standalone_question text check (length(standalone_question) <= 5000),
    analysis_mode text not null default 'balanced'
        check (analysis_mode in ('quick', 'balanced', 'deep')),
    evidence_refs jsonb not null default '[]'::jsonb
        check (jsonb_typeof(evidence_refs) = 'array'),
    created_at timestamptz not null default now(),
    unique (conversation_id, position),
    foreign key (conversation_id, user_id)
        references public.mkh_user_conversations(id, user_id) on delete cascade
);

create index if not exists mkh_user_messages_thread
    on public.mkh_user_messages (user_id, conversation_id, position);

alter table public.mkh_user_conversations enable row level security;
alter table public.mkh_user_messages enable row level security;

revoke all on public.mkh_user_conversations from public, anon;
revoke all on public.mkh_user_messages from public, anon;
grant select, insert, update, delete on public.mkh_user_conversations to authenticated;
grant select, insert, delete on public.mkh_user_messages to authenticated;

drop policy if exists mkh_conversations_select_own on public.mkh_user_conversations;
create policy mkh_conversations_select_own on public.mkh_user_conversations
    for select to authenticated using (user_id = (select auth.uid()));
drop policy if exists mkh_conversations_insert_own on public.mkh_user_conversations;
create policy mkh_conversations_insert_own on public.mkh_user_conversations
    for insert to authenticated with check (user_id = (select auth.uid()));
drop policy if exists mkh_conversations_update_own on public.mkh_user_conversations;
create policy mkh_conversations_update_own on public.mkh_user_conversations
    for update to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));
drop policy if exists mkh_conversations_delete_own on public.mkh_user_conversations;
create policy mkh_conversations_delete_own on public.mkh_user_conversations
    for delete to authenticated using (user_id = (select auth.uid()));

drop policy if exists mkh_messages_select_own on public.mkh_user_messages;
create policy mkh_messages_select_own on public.mkh_user_messages
    for select to authenticated using (user_id = (select auth.uid()));
drop policy if exists mkh_messages_insert_own on public.mkh_user_messages;
create policy mkh_messages_insert_own on public.mkh_user_messages
    for insert to authenticated with check (user_id = (select auth.uid()));
drop policy if exists mkh_messages_delete_own on public.mkh_user_messages;
create policy mkh_messages_delete_own on public.mkh_user_messages
    for delete to authenticated using (user_id = (select auth.uid()));
