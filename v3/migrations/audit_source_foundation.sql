-- READ ONLY. Run only in GIZ MKH hofoubbmepacdljeablj.
-- Inventory structure/count estimates; never read private conversation content.
select current_database(),current_user,version();
select schemaname,relname,n_live_tup,last_analyze,last_autoanalyze
  from pg_stat_user_tables where schemaname='public' order by relname;
select table_name,column_name,data_type,is_nullable
  from information_schema.columns where table_schema='public' order by table_name,ordinal_position;
select tablename,policyname,roles,cmd,qual,with_check
  from pg_policies where schemaname='public' order by tablename,policyname;
select c.relname,c.relrowsecurity,c.relforcerowsecurity,c.reloptions
  from pg_class c join pg_namespace n on n.oid=c.relnamespace
  where n.nspname='public' and c.relkind in ('r','v') order by c.relname;
select p.proname,p.prosecdef,p.proconfig,pg_get_function_identity_arguments(p.oid) arguments
  from pg_proc p join pg_namespace n on n.oid=p.pronamespace
  where n.nspname='public' order by p.proname;
-- Run the following only after the inventory confirms these existing relations/columns.
-- select count(*),min(publication_date),max(publication_date) from public.documents;
-- select count(*),count(distinct document_id) from public.chunks;
-- select count(*),max(last_synced_at) from public.fongim_projects;
-- select count(*) from public.fongim_project_locations where is_present_in_source;
