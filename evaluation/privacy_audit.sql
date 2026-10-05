-- MKH qualification: exact GIZ project hofoubbmepacdljeablj only.
-- All identities/messages below are synthetic. No passwords, tokens, API keys,
-- existing account histories, permission changes, or external Auth calls.
-- Execute the whole transaction as the existing authorized SQL admin.
-- The final ROLLBACK removes every synthetic row, including trigger effects.
-- This tests database RLS and owner/thread integrity; it does not certify the
-- browser sign-in flow or replace a separately recorded live API smoke test.
BEGIN;
SET LOCAL statement_timeout = '20s';
SET LOCAL lock_timeout = '2s';
-- A collision stops the transaction, never touching an existing account.
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM auth.users WHERE id IN
  ('b017f7e4-0990-4388-9d6c-45deaf80b101','b017f7e4-0990-4388-9d6c-45deaf80b102')) THEN
  RAISE EXCEPTION 'Synthetic audit UUID collision';
 END IF;
 IF EXISTS (SELECT 1 FROM public.mkh_user_conversations WHERE id =
  'b017f7e4-0990-4388-9d6c-45deaf80b103') THEN
  RAISE EXCEPTION 'Synthetic audit thread UUID collision';
 END IF;
END $$;
INSERT INTO auth.users (id,aud,role,email,created_at,updated_at)
VALUES ('b017f7e4-0990-4388-9d6c-45deaf80b101','authenticated','authenticated','mkh-benchmark-a@example.invalid',now(),now()),
       ('b017f7e4-0990-4388-9d6c-45deaf80b102','authenticated','authenticated','mkh-benchmark-b@example.invalid',now(),now());
SET LOCAL ROLE authenticated;
SET LOCAL request.jwt.claim.sub = 'b017f7e4-0990-4388-9d6c-45deaf80b101';
SET LOCAL request.jwt.claims = '{"sub":"b017f7e4-0990-4388-9d6c-45deaf80b101","role":"authenticated"}';
INSERT INTO public.mkh_user_conversations (id,user_id,title)
VALUES ('b017f7e4-0990-4388-9d6c-45deaf80b103','b017f7e4-0990-4388-9d6c-45deaf80b101','Synthetic MKH qualification');
INSERT INTO public.mkh_user_messages (conversation_id,user_id,position,role,content)
VALUES ('b017f7e4-0990-4388-9d6c-45deaf80b103','b017f7e4-0990-4388-9d6c-45deaf80b101',1,'user','Synthetic public benchmark question');
DO $$ BEGIN
 IF (SELECT count(*) FROM public.mkh_user_conversations WHERE id='b017f7e4-0990-4388-9d6c-45deaf80b103') <> 1
 OR (SELECT count(*) FROM public.mkh_user_messages WHERE conversation_id='b017f7e4-0990-4388-9d6c-45deaf80b103') <> 1 THEN
  RAISE EXCEPTION 'Owner access failed';
 END IF;
END $$;
SET LOCAL request.jwt.claim.sub = 'b017f7e4-0990-4388-9d6c-45deaf80b102';
SET LOCAL request.jwt.claims = '{"sub":"b017f7e4-0990-4388-9d6c-45deaf80b102","role":"authenticated"}';
DO $$ DECLARE affected integer; BEGIN
 IF EXISTS (SELECT 1 FROM public.mkh_user_conversations WHERE id='b017f7e4-0990-4388-9d6c-45deaf80b103')
 OR EXISTS (SELECT 1 FROM public.mkh_user_messages WHERE conversation_id='b017f7e4-0990-4388-9d6c-45deaf80b103') THEN
  RAISE EXCEPTION 'Cross-user read allowed';
 END IF;
 UPDATE public.mkh_user_conversations SET title='Synthetic blocked mutation' WHERE id='b017f7e4-0990-4388-9d6c-45deaf80b103';
 GET DIAGNOSTICS affected = ROW_COUNT;
 IF affected <> 0 THEN RAISE EXCEPTION 'Cross-user update allowed'; END IF;
 DELETE FROM public.mkh_user_messages WHERE conversation_id='b017f7e4-0990-4388-9d6c-45deaf80b103';
 GET DIAGNOSTICS affected = ROW_COUNT;
 IF affected <> 0 THEN RAISE EXCEPTION 'Cross-user message delete allowed'; END IF;
 DELETE FROM public.mkh_user_conversations WHERE id='b017f7e4-0990-4388-9d6c-45deaf80b103';
 GET DIAGNOSTICS affected = ROW_COUNT;
 IF affected <> 0 THEN RAISE EXCEPTION 'Cross-user thread delete allowed'; END IF;
 BEGIN
  INSERT INTO public.mkh_user_messages (conversation_id,user_id,position,role,content)
  VALUES ('b017f7e4-0990-4388-9d6c-45deaf80b103','b017f7e4-0990-4388-9d6c-45deaf80b101',2,'user','Synthetic blocked owner spoof');
  RAISE EXCEPTION 'Cross-user owner spoof allowed';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
  INSERT INTO public.mkh_user_messages (conversation_id,user_id,position,role,content)
  VALUES ('b017f7e4-0990-4388-9d6c-45deaf80b103','b017f7e4-0990-4388-9d6c-45deaf80b102',2,'user','Synthetic blocked thread link');
  RAISE EXCEPTION 'Cross-user thread link allowed';
 EXCEPTION WHEN foreign_key_violation OR insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
SET LOCAL ROLE anon;
SET LOCAL request.jwt.claim.sub = '';
SET LOCAL request.jwt.claims = '{}';
DO $$ BEGIN
 BEGIN
  IF EXISTS (SELECT 1 FROM public.mkh_user_messages WHERE conversation_id='b017f7e4-0990-4388-9d6c-45deaf80b103') THEN
   RAISE EXCEPTION 'Anonymous message read allowed';
  END IF;
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
  IF EXISTS (SELECT 1 FROM public.mkh_user_conversations WHERE id='b017f7e4-0990-4388-9d6c-45deaf80b103') THEN
   RAISE EXCEPTION 'Anonymous thread read allowed';
  END IF;
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
SELECT 'PASS: synthetic owner, cross-user and anonymous RLS checks; rollback follows' AS audit_result;
ROLLBACK;
