create schema if not exists mkh_v3_private;
revoke all on schema mkh_v3_private from public, anon, authenticated;

create table public.mkh_v3_archived_turns (
    conversation_id uuid not null references public.mkh_v3_conversations(id) on delete cascade,
    ordinal integer not null check (ordinal > 0),
    owner_id uuid not null references auth.users(id) on delete cascade,
    turn jsonb not null,
    primary key (conversation_id, ordinal)
);
create index mkh_v3_archived_owner on public.mkh_v3_archived_turns(owner_id, conversation_id);
alter table public.mkh_v3_archived_turns enable row level security;
revoke all on public.mkh_v3_archived_turns from public, anon, authenticated;
grant select on public.mkh_v3_archived_turns to authenticated;
create policy mkh_v3_read_own_archive on public.mkh_v3_archived_turns for select to authenticated
    using ((select auth.uid()) = owner_id);

create function mkh_v3_private.archive_displaced_turns() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
    if new.revision = old.revision + 1 and new.owner_id = old.owner_id then
        insert into public.mkh_v3_archived_turns(conversation_id, ordinal, owner_id, turn)
        select old.id, old.revision - jsonb_array_length(old.turns) + t.n, old.owner_id, t.entry
        from jsonb_array_elements(old.turns) with ordinality as t(entry, n)
        where old.revision - jsonb_array_length(old.turns) + t.n between 1 and new.revision - jsonb_array_length(new.turns)
        on conflict do nothing;
    end if;
    return new;
end;
$$;
revoke all on function mkh_v3_private.archive_displaced_turns() from public, anon, authenticated;
create trigger mkh_v3_preserve_turns after update of turns on public.mkh_v3_conversations
    for each row execute function mkh_v3_private.archive_displaced_turns();

create function public.mkh_v3_find_archived_work(chat uuid, terms text) returns setof public.mkh_v3_archived_turns
language sql stable security invoker set search_path = '' as $$
    select a.* from public.mkh_v3_archived_turns a
    where a.conversation_id = chat and a.owner_id = (select auth.uid())
      and (btrim(terms) = '' or to_tsvector('simple', concat_ws(' ', a.turn->>'prompt', a.turn->>'answer'))
           @@ websearch_to_tsquery('simple', left(terms, 250)))
    order by a.ordinal desc limit 3
$$;
revoke all on function public.mkh_v3_find_archived_work(uuid, text) from public, anon, authenticated;
grant execute on function public.mkh_v3_find_archived_work(uuid, text) to authenticated;
