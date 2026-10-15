"""Admin boundaries with a fake provider; no real messages or grants."""
import types
import os
import unittest
from unittest.mock import Mock, patch, AsyncMock
from starlette.testclient import TestClient
from starlette.responses import JSONResponse
import web_api

ORIGIN='https://mali-knowledge-hub.onrender.com'
IID='11111111-1111-4111-8111-111111111111'
UID='22222222-2222-4222-8222-222222222222'
PASSWORD='a test only long passphrase'

def person(confirmed=True):
    return types.SimpleNamespace(id=UID,email='recipient@example.org',
        email_confirmed_at='2026-10-15' if confirmed else None,user_metadata={'role':'admin'})

class AdminAPITests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(web_api.app,base_url=ORIGIN)
        self.store=Mock();self.store.is_admin.return_value=True;self.store.pending.return_value=None
        self.store.create.return_value={'id':IID,'existing':False,'confirmed':False}
        self.store.check.return_value=True;self.store.accept.return_value=True
        self.provider=Mock()
        self.patches=[patch.object(web_api,'actor',new=AsyncMock(return_value=(person(),'token',None))),
            patch.object(web_api,'admin_store',return_value=self.store),
            patch.object(web_api,'auth_client',return_value=types.SimpleNamespace(auth=self.provider))]
        self.actor_mock=self.patches[0].start()
        for p in self.patches[1:]:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.client.close()
    def post(self,path,data=None,origin=ORIGIN,method='POST'):
        return self.client.request(method,'/api/admin/'+path,json=data or {},headers={'Origin':origin})
    def test_cross_origin_mutations_never_reach_provider(self):
        for path in ['invitations','invitations/accept','source-requests',f'documents/{IID}/reprocess']:
            with self.subTest(path=path):self.assertEqual(self.post(path,origin='https://evil.example').status_code,403)
        self.store.create.assert_not_called();self.store.accept.assert_not_called()
    def test_guest_cannot_read_or_mutate_admin_data(self):
        self.actor_mock.return_value=(None,None,None)
        self.assertEqual(self.client.get('/api/admin/overview').status_code,401)
        self.assertEqual(self.post('invitations',{'email':'a@example.org'}).status_code,401)
        self.assertEqual(self.client.post('/api/admin/documents',content=b'data',headers={'Origin':ORIGIN,'Content-Type':'application/octet-stream'}).status_code,401)
        self.assertEqual(self.client.get('/api/admin/status').json(),{'authenticated':False,'is_admin':False})
        self.store.create.assert_not_called();self.store.overview.assert_not_called()
    def test_editable_admin_metadata_never_grants_rights(self):
        self.store.is_admin.return_value=False
        self.assertEqual(self.client.get('/api/admin/overview').status_code,403)
        self.assertEqual(self.post('invitations',{'email':'a@example.org','role':'admin'}).status_code,403)
        self.store.create.assert_not_called()
    def test_unverified_identity_is_not_an_admin(self):
        self.actor_mock.return_value=(person(False),'token',None)
        self.assertEqual(self.post('invitations',{'email':'a@example.org'}).status_code,401)
        self.store.is_admin.assert_not_called()
    def test_role_lookup_failure_fails_closed(self):
        self.store.is_admin.side_effect=RuntimeError('private DB detail')
        r=self.post('invitations',{'email':'a@example.org'});self.assertEqual(r.status_code,503)
        self.assertNotIn('private DB',r.text);self.store.create.assert_not_called()
    def test_new_invite_sends_mail_without_granting_role(self):
        r=self.post('invitations',{'email':' Recipient@Example.org ','role':'admin'})
        self.assertEqual(r.status_code,201);self.store.create.assert_called_once_with(UID,'recipient@example.org')
        self.store.db.auth.admin.invite_user_by_email.assert_called_once_with('recipient@example.org',{'redirect_to':ORIGIN+'/'})
        self.store.delivered.assert_called_once_with(IID,True);self.store.accept.assert_not_called()
    def test_existing_recipient_uses_link_without_account_creation(self):
        self.store.create.return_value={'id':IID,'existing':True,'confirmed':True}
        self.assertEqual(self.post('invitations',{'email':'recipient@example.org'}).status_code,201)
        self.provider.sign_in_with_otp.assert_called_once_with({'email':'recipient@example.org','options':{'should_create_user':False,'email_redirect_to':ORIGIN+'/'}})
        self.store.db.auth.admin.invite_user_by_email.assert_not_called()
    def test_unverified_existing_recipient_gets_confirmation(self):
        self.store.create.return_value={'id':IID,'existing':True,'confirmed':False}
        self.assertEqual(self.post('invitations',{'email':'recipient@example.org'}).status_code,201)
        self.provider.resend.assert_called_once_with({'type':'signup','email':'recipient@example.org','options':{'email_redirect_to':ORIGIN+'/'}})
    def test_mail_failure_recorded_without_role_grant(self):
        self.store.db.auth.admin.invite_user_by_email.side_effect=RuntimeError('secret token')
        r=self.post('invitations',{'email':'recipient@example.org'})
        self.assertEqual(r.status_code,503);self.assertNotIn('secret token',r.text)
        self.store.delivered.assert_called_once_with(IID,False);self.store.accept.assert_not_called()
    def test_invalid_invitation_never_changes_password(self):
        self.store.check.return_value=False
        with patch.object(web_api,'update_password',new=AsyncMock()) as save:
            self.assertEqual(self.post('invitations/accept',{'invitation_id':IID,'password':PASSWORD}).status_code,403)
            save.assert_not_called();self.store.accept.assert_not_called()
    def test_weak_password_rejected_before_acceptance(self):
        self.assertEqual(self.post('invitations/accept',{'invitation_id':IID,'password':'short'}).status_code,400)
        self.store.check.assert_not_called();self.store.accept.assert_not_called()
    def test_failed_password_save_cannot_grant_role(self):
        with patch.object(web_api,'update_password',new=AsyncMock(return_value=JSONResponse({'error':'failed'},status_code=503))):
            self.assertEqual(self.post('invitations/accept',{'invitation_id':IID,'password':PASSWORD}).status_code,503)
        self.store.accept.assert_not_called()
    def test_accept_requires_password_save_and_preserves_secure_cookie(self):
        saved=JSONResponse({});saved.set_cookie('mkh_access','fresh',secure=True,httponly=True,samesite='lax')
        with patch.object(web_api,'update_password',new=AsyncMock(return_value=saved)):
            r=self.post('invitations/accept',{'invitation_id':IID,'password':PASSWORD})
        self.assertEqual(r.status_code,200);self.store.check.assert_called_once_with(UID,IID)
        self.store.accept.assert_called_once_with(UID,IID);self.assertIn('HttpOnly',r.headers['set-cookie'])
        self.assertNotIn(PASSWORD,r.text)
    def test_revocation_race_after_password_save_cannot_report_ready(self):
        self.store.accept.side_effect=RuntimeError('revoked')
        with patch.object(web_api,'update_password',new=AsyncMock(return_value=JSONResponse({}))):
            r=self.post('invitations/accept',{'invitation_id':IID,'password':PASSWORD})
        self.assertEqual(r.status_code,409);self.assertIn('password was saved',r.json()['error'])
    def test_nonadmin_only_gets_their_pending_invitation(self):
        self.store.is_admin.return_value=False;self.store.pending.return_value={'id':IID,'email':'recipient@example.org'}
        self.assertEqual(self.client.get('/api/admin/status').status_code,200)
        self.store.pending.assert_called_once_with('recipient@example.org');self.store.overview.assert_not_called()
    def test_source_registration_does_not_claim_publication(self):
        self.store.source_request.return_value=IID
        r=self.post('source-requests',{'title':'Public feed','url':'https://data.example.org/feed'})
        self.assertEqual(r.status_code,201);self.assertIn('No data has been fetched',r.json()['message'])
    def test_source_rejects_embedded_secrets_and_private_hosts(self):
        for url in ['http://example.org','https://name:pass@example.org','https://example.org/?key=secret','https://example.org/#secret','https://127.0.0.1/feed','https://localhost/feed','https://169.254.169.254/feed']:
            with self.subTest(url=url):self.assertEqual(self.post('source-requests',{'title':'Data','url':url}).status_code,400)
        self.store.source_request.assert_not_called()
    def test_admin_page_is_public_shell_without_account_records(self):
        r=self.client.get('/admin');self.assertEqual(r.status_code,200)
        self.assertIn('Administrator sign-in',r.text);self.assertNotIn('recipient@example.org',r.text)
        self.store.overview.assert_not_called()
    def test_document_upload_records_verified_actor_and_queues_existing_pipeline(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fake-test-key'}), \
             patch('ingestion.create_job',return_value=IID) as create, \
             patch('ingestion_worker.schedule_job') as schedule:
            r=self.client.post('/api/admin/documents',content=b'%PDF-test',headers={
                'Origin':ORIGIN,'Content-Type':'application/octet-stream','X-MKH-Filename':'source.pdf',
                'X-MKH-User':'forged-user'})
        self.assertEqual(r.status_code,202)
        create.assert_called_once_with(self.store.db,'source.pdf',b'%PDF-test',UID)
        self.store.audit.assert_called_once_with(UID,'document_uploaded',IID)
        self.assertEqual(schedule.call_args.args[-1],IID)
    def test_oversized_upload_never_creates_a_job(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fake-test-key'}),patch('ingestion.create_job') as create:
            r=self.client.post('/api/admin/documents',content=b'x'*(20*1024*1024+1),headers={
                'Origin':ORIGIN,'Content-Type':'application/octet-stream','X-MKH-Filename':'large.pdf'})
        self.assertEqual(r.status_code,413);create.assert_not_called()
    def test_ordinary_user_cannot_upload_or_reprocess(self):
        self.store.is_admin.return_value=False
        with patch('ingestion.create_job') as create,patch('ingestion_worker.schedule_job') as schedule:
            self.assertEqual(self.client.post('/api/admin/documents',content=b'data',headers={
                'Origin':ORIGIN,'Content-Type':'application/octet-stream','X-MKH-Filename':'source.pdf'}).status_code,403)
            self.assertEqual(self.post(f'documents/{IID}/reprocess').status_code,403)
        create.assert_not_called();schedule.assert_not_called()
    def test_reprocess_validates_corrections_and_audits_verified_actor(self):
        self.store.db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data=[{'id':IID,'status':'ready'}]
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fake-test-key'}),patch('ingestion_worker.schedule_job',return_value=True) as schedule:
            self.assertEqual(self.post(f'documents/{IID}/reprocess',{'corrections':{'status':'active'}}).status_code,400)
            self.assertEqual(self.post(f'documents/{IID}/reprocess',{'corrections':{'title':'Reviewed title'}}).status_code,202)
        self.store.audit.assert_called_once_with(UID,'document_reprocess_requested',IID)
        self.assertEqual(schedule.call_args.kwargs,{'corrections':{'title':'Reviewed title'}})
