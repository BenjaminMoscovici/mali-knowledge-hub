begin;

do $test$
declare a uuid:='f1000000-0000-4000-8000-000000000001'; b uuid:='f1000000-0000-4000-8000-000000000002';
 c uuid:='f1000000-0000-4000-8000-000000000003'; d uuid:='f1000000-0000-4000-8000-000000000004';
 boot text[]:=array['admin-qualification@example.invalid']; i uuid; j uuid; s uuid;
begin
 insert into auth.users(id,email,email_confirmed_at,raw_user_meta_data) values
 (a,'admin-qualification@example.invalid',now(),'{}'),
 (b,'invite-qualification@example.invalid',now(),'{}'),
 (c,'ordinary-qualification@example.invalid',now(),'{"role":"admin"}'),
 (d,'second-qualification@example.invalid',now(),'{}');
 if not public.mkh_admin_allowed(a,boot) or public.mkh_admin_allowed(c,boot) then raise exception 'Bootstrap/metadata gate failed'; end if;
 if exists(select 1 from pg_class t join pg_namespace n on n.oid=t.relnamespace where n.nspname='public' and t.relname like 'mkh_admin_%' and t.relkind='r' and (not t.relrowsecurity or has_table_privilege('anon',t.oid,'SELECT') or has_table_privilege('authenticated',t.oid,'INSERT') or has_table_privilege('authenticated',t.oid,'SELECT'))) then raise exception 'Table boundary failed'; end if;
 if exists(select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname like 'mkh_admin_%' and (p.prosecdef or has_function_privilege('anon',p.oid,'EXECUTE') or has_function_privilege('authenticated',p.oid,'EXECUTE'))) then raise exception 'RPC boundary failed'; end if;
 i:=(public.mkh_admin_invite(a,'invite-qualification@example.invalid',boot)->>'id')::uuid;
 if public.mkh_admin_check_invite(b,i,boot) or public.mkh_admin_allowed(b,boot) then raise exception 'Unsent invite granted rights'; end if;
 perform public.mkh_admin_delivery(i,true);
 if not public.mkh_admin_check_invite(b,i,boot) or public.mkh_admin_check_invite(c,i,boot) then raise exception 'Recipient identity gate failed'; end if;
 begin perform public.mkh_admin_accept(c,i,boot); raise exception 'Wrong recipient accepted';
 exception when raise_exception then if sqlerrm<>'Invitation unavailable' then raise; end if; end;
 update auth.users set email_confirmed_at=null where id=b;
 if public.mkh_admin_check_invite(b,i,boot) then raise exception 'Unverified recipient accepted'; end if;
 update auth.users set email_confirmed_at=now() where id=b;
 update auth.users set email='changed-qualification@example.invalid' where id=a;
 if public.mkh_admin_check_invite(b,i,boot) then raise exception 'Unauthorized inviter retained grant authority'; end if;
 update auth.users set email='admin-qualification@example.invalid' where id=a;
 perform public.mkh_admin_accept(b,i,boot);
 if not public.mkh_admin_allowed(b,boot) then raise exception 'Acceptance failed'; end if;
 begin perform public.mkh_admin_accept(b,i,boot); raise exception 'Invitation replay accepted';
 exception when raise_exception then if sqlerrm<>'Invitation unavailable' then raise; end if; end;
 j:=(public.mkh_admin_invite(b,'ordinary-qualification@example.invalid',boot)->>'id')::uuid;
 perform public.mkh_admin_delivery(j,true);
 update public.mkh_admin_invitations set expires_at=now()-interval '1 second' where id=j;
 if public.mkh_admin_check_invite(c,j,boot) then raise exception 'Expired invitation accepted'; end if;
 begin perform public.mkh_admin_accept(c,j,boot); raise exception 'Expired invite granted role';
 exception when raise_exception then if sqlerrm<>'Invitation unavailable' then raise; end if; end;
 perform public.mkh_admin_revoke(a,j,boot);
 if public.mkh_admin_check_invite(c,j,boot) then raise exception 'Revoked invite accepted'; end if;
 j:=(public.mkh_admin_invite(b,'second-qualification@example.invalid',boot)->>'id')::uuid;
 perform public.mkh_admin_delivery(j,false);
 if public.mkh_admin_check_invite(d,j,boot) or public.mkh_admin_allowed(d,boot) then raise exception 'Failed mail granted rights'; end if;
 s:=public.mkh_admin_source_request(b,'{"title":"Qualification only","url":"https://example.invalid/source"}',boot);
 if not exists(select 1 from public.mkh_admin_source_requests where id=s and status='awaiting_review' and submitted_by=b) then raise exception 'Source review/audit failed'; end if;
 if not exists(select 1 from public.mkh_admin_audit where actor_id=b and action='invitation_accepted' and target_id=i) then raise exception 'Acceptance audit missing'; end if;
 update auth.users set email='changed-recipient@example.invalid' where id=b;
 if public.mkh_admin_allowed(b,boot) then raise exception 'Changed email retained stale role'; end if;
end $test$;
set local role service_role;
do $test$ declare i uuid; begin
 if not public.mkh_admin_allowed('f1000000-0000-4000-8000-000000000001',array['admin-qualification@example.invalid']) then raise exception 'Actual service role cannot verify bootstrap'; end if;
 i:=(public.mkh_admin_invite('f1000000-0000-4000-8000-000000000001','second-qualification@example.invalid',array['admin-qualification@example.invalid'])->>'id')::uuid;
 perform public.mkh_admin_delivery(i,true);
 perform public.mkh_admin_accept('f1000000-0000-4000-8000-000000000004',i,array['admin-qualification@example.invalid']);
 if not public.mkh_admin_allowed('f1000000-0000-4000-8000-000000000004',array['admin-qualification@example.invalid']) then raise exception 'Actual service-role acceptance failed'; end if;
 if has_column_privilege('service_role','auth.users','encrypted_password','SELECT') then raise exception 'Password column unexpectedly readable'; end if;
end $test$;
reset role;
set local role anon;
do $test$ begin
 begin perform public.mkh_admin_allowed('f1000000-0000-4000-8000-000000000001',array['admin-qualification@example.invalid']);raise exception 'Anon invoked privileged RPC';
 exception when insufficient_privilege then null; end;
 begin perform 1 from public.mkh_admin_invitations;raise exception 'Anon read invitations';
 exception when insufficient_privilege then null; end;
end $test$;
reset role;
set local role authenticated;
do $test$ begin
 begin perform public.mkh_admin_invite('f1000000-0000-4000-8000-000000000003','attacker@example.invalid',array['ordinary-qualification@example.invalid']);raise exception 'Authenticated user invoked privileged RPC';
 exception when insufficient_privilege then null; end;
 begin insert into public.mkh_admin_members(user_id,email) values('f1000000-0000-4000-8000-000000000003','ordinary-qualification@example.invalid');raise exception 'Authenticated user self-promoted';
 exception when insufficient_privilege then null; end;
end $test$;
reset role;
rollback;
select 'passed; all schema, synthetic identities, invitations, roles and source requests rolled back' as qualification;
