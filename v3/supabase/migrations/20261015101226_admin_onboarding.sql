-- Additive, server-only records. No role grants or invitations are seeded.
begin;
create table public.mkh_admin_members (
 user_id uuid primary key references auth.users(id) on delete cascade,
 email text not null check(email=lower(email)),
 granted_by uuid references auth.users(id) on delete set null,
 created_at timestamptz not null default now()
);
create table public.mkh_admin_invitations (
 id uuid primary key default gen_random_uuid(),
 email text not null check(email=lower(email) and length(email)<=254),
 invited_by uuid references auth.users(id) on delete set null,
 created_at timestamptz not null default now(),
 expires_at timestamptz not null default (now()+interval '7 days'),
 status text not null default 'sending' check(status in ('sending','pending','failed','accepted','revoked','expired')),
 accepted_by uuid references auth.users(id) on delete set null,
 accepted_at timestamptz
);
create unique index mkh_admin_open_invite on public.mkh_admin_invitations(email) where status in ('sending','pending');
create table public.mkh_admin_source_requests (
 id uuid primary key default gen_random_uuid(),
 title text not null check(length(title) between 1 and 160),
 url text not null check(url like 'https://%' and length(url)<=1000),
 organization text not null default '', notes text not null default '',
 status text not null default 'awaiting_review' check(status='awaiting_review'),
 submitted_by uuid references auth.users(id) on delete set null,
 created_at timestamptz not null default now()
);
create table public.mkh_admin_audit (
 id uuid primary key default gen_random_uuid(),
 actor_id uuid references auth.users(id) on delete set null,
 action text not null, target_id uuid,
 created_at timestamptz not null default now()
);
alter table public.mkh_admin_members enable row level security;
alter table public.mkh_admin_invitations enable row level security;
alter table public.mkh_admin_source_requests enable row level security;
alter table public.mkh_admin_audit enable row level security;
revoke all on public.mkh_admin_members,public.mkh_admin_invitations,public.mkh_admin_source_requests,public.mkh_admin_audit from public,anon,authenticated;
grant select,insert,update,delete on public.mkh_admin_members,public.mkh_admin_invitations,public.mkh_admin_source_requests,public.mkh_admin_audit to service_role;
-- The existing server role can already administer Auth through its API. Its
-- invoker RPCs need only these identity columns, never passwords or tokens.
grant select(id,email,email_confirmed_at) on auth.users to service_role;

create function public.mkh_admin_allowed(p_user uuid,p_bootstrap text[]) returns boolean
language sql stable security invoker set search_path='' as $$
 select exists(select 1 from auth.users u where u.id=p_user and u.email_confirmed_at is not null
 and (lower(u.email)=any(p_bootstrap) or exists(select 1 from public.mkh_admin_members m where m.user_id=u.id and m.email=lower(u.email))));
$$;

create function public.mkh_admin_invite(p_actor uuid,p_email text,p_bootstrap text[]) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare v_id uuid; v_target uuid; v_confirmed boolean;
begin
 if not public.mkh_admin_allowed(p_actor,p_bootstrap) then raise exception 'Administrator required'; end if;
 if p_email<>lower(p_email) or p_email !~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$' or length(p_email)>254 then raise exception 'Invalid email'; end if;
 select id,email_confirmed_at is not null into v_target,v_confirmed from auth.users where lower(email)=p_email;
 if public.mkh_admin_allowed(v_target,p_bootstrap) then raise exception 'Already an administrator'; end if;
 update public.mkh_admin_invitations set status='expired' where email=p_email and expires_at<=now() and status in ('pending','sending');
 insert into public.mkh_admin_invitations(email,invited_by) values(p_email,p_actor) returning id into v_id;
 insert into public.mkh_admin_audit(actor_id,action,target_id) values(p_actor,'invitation_created',v_id);
 return jsonb_build_object('id',v_id,'existing',v_target is not null,'confirmed',coalesce(v_confirmed,false));
end; $$;

create function public.mkh_admin_delivery(p_invitation uuid,p_ok boolean) returns void
language plpgsql security invoker set search_path='' as $$
declare v_actor uuid;
begin
 update public.mkh_admin_invitations set status=case when p_ok then 'pending' else 'failed' end
 where id=p_invitation and status='sending' returning invited_by into v_actor;
 if not found then raise exception 'Invitation changed'; end if;
 insert into public.mkh_admin_audit(actor_id,action,target_id) values(v_actor,case when p_ok then 'invitation_email_requested' else 'invitation_email_failed' end,p_invitation);
end; $$;

create function public.mkh_admin_check_invite(p_user uuid,p_invitation uuid,p_bootstrap text[]) returns boolean
language sql stable security invoker set search_path='' as $$
 select exists(select 1 from public.mkh_admin_invitations i join auth.users u on lower(u.email)=i.email
 where i.id=p_invitation and i.status='pending' and i.expires_at>now() and u.id=p_user
 and u.email_confirmed_at is not null and public.mkh_admin_allowed(i.invited_by,p_bootstrap));
$$;

create function public.mkh_admin_accept(p_user uuid,p_invitation uuid,p_bootstrap text[]) returns boolean
language plpgsql security invoker set search_path='' as $$
declare v_inv public.mkh_admin_invitations%rowtype;
begin
 select * into v_inv from public.mkh_admin_invitations where id=p_invitation for update;
 if not public.mkh_admin_check_invite(p_user,p_invitation,p_bootstrap) then raise exception 'Invitation unavailable'; end if;
 insert into public.mkh_admin_members(user_id,email,granted_by) values(p_user,v_inv.email,v_inv.invited_by)
 on conflict(user_id) do update set email=excluded.email,granted_by=excluded.granted_by;
 update public.mkh_admin_invitations set status='accepted',accepted_by=p_user,accepted_at=now() where id=p_invitation;
 insert into public.mkh_admin_audit(actor_id,action,target_id) values(p_user,'invitation_accepted',p_invitation);
 return true;
end; $$;

create function public.mkh_admin_revoke(p_actor uuid,p_invitation uuid,p_bootstrap text[]) returns boolean
language plpgsql security invoker set search_path='' as $$
begin
 if not public.mkh_admin_allowed(p_actor,p_bootstrap) then raise exception 'Administrator required'; end if;
 update public.mkh_admin_invitations set status='revoked' where id=p_invitation and status in ('sending','pending');
 if not found then raise exception 'Invitation unavailable'; end if;
 insert into public.mkh_admin_audit(actor_id,action,target_id) values(p_actor,'invitation_revoked',p_invitation);
 return true;
end; $$;

create function public.mkh_admin_source_request(p_actor uuid,p_data jsonb,p_bootstrap text[]) returns uuid
language plpgsql security invoker set search_path='' as $$
declare v_id uuid;
begin
 if not public.mkh_admin_allowed(p_actor,p_bootstrap) then raise exception 'Administrator required'; end if;
 insert into public.mkh_admin_source_requests(title,url,organization,notes,submitted_by)
 values(p_data->>'title',p_data->>'url',coalesce(p_data->>'organization',''),coalesce(p_data->>'notes',''),p_actor) returning id into v_id;
 insert into public.mkh_admin_audit(actor_id,action,target_id) values(p_actor,'source_requested',v_id);
 return v_id;
end; $$;

create function public.mkh_admin_record(p_actor uuid,p_action text,p_target uuid,p_bootstrap text[]) returns void
language plpgsql security invoker set search_path='' as $$
begin
 if not public.mkh_admin_allowed(p_actor,p_bootstrap) or p_action not in ('document_uploaded','document_reprocess_requested') then raise exception 'Invalid audit action'; end if;
 insert into public.mkh_admin_audit(actor_id,action,target_id) values(p_actor,p_action,p_target);
end; $$;

revoke all on function public.mkh_admin_allowed(uuid,text[]),public.mkh_admin_invite(uuid,text,text[]),public.mkh_admin_delivery(uuid,boolean),public.mkh_admin_check_invite(uuid,uuid,text[]),public.mkh_admin_accept(uuid,uuid,text[]),public.mkh_admin_revoke(uuid,uuid,text[]),public.mkh_admin_source_request(uuid,jsonb,text[]),public.mkh_admin_record(uuid,text,uuid,text[]) from public,anon,authenticated;
grant execute on function public.mkh_admin_allowed(uuid,text[]),public.mkh_admin_invite(uuid,text,text[]),public.mkh_admin_delivery(uuid,boolean),public.mkh_admin_check_invite(uuid,uuid,text[]),public.mkh_admin_accept(uuid,uuid,text[]),public.mkh_admin_revoke(uuid,uuid,text[]),public.mkh_admin_source_request(uuid,jsonb,text[]),public.mkh_admin_record(uuid,text,uuid,text[]) to service_role;
commit;
