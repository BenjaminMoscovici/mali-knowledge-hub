create table public.mkh_v3_memory (
    owner_id uuid primary key default auth.uid() references auth.users(id) on delete cascade,
    enabled boolean not null default false,
    notes text not null check (char_length(notes) between 1 and 2000)
);

alter table public.mkh_v3_memory enable row level security;
revoke all on public.mkh_v3_memory from public, anon, authenticated;
grant select, delete on public.mkh_v3_memory to authenticated;
grant insert (enabled, notes), update (enabled, notes) on public.mkh_v3_memory to authenticated;

create policy mkh_v3_own_memory on public.mkh_v3_memory for all to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
