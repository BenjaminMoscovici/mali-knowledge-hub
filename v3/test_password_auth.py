"""Password-account boundaries. Fake provider only: no emails or real accounts."""
import types
import unittest
from unittest.mock import Mock, patch

from starlette.testclient import TestClient
from supabase_auth.errors import AuthApiError

import web_api

ORIGIN = "https://mali-knowledge-hub.onrender.com"
PASSWORD = "test-only long passphrase"


def user(uid="existing-id", confirmed=True):
    return types.SimpleNamespace(id=uid, email="person@example.org",
        email_confirmed_at="2026-10-13T00:00:00Z" if confirmed else None,
        user_metadata={"username": "Researcher", "role": "admin"})


def result(account=None, session=True):
    account = account or user()
    saved = types.SimpleNamespace(user=account, access_token="new-access", refresh_token="new-refresh") if session else None
    return types.SimpleNamespace(user=account, session=saved)


class PasswordAccountTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(web_api.app, base_url=ORIGIN)
        self.provider = Mock()
        self.provider.sign_up.return_value = result(session=False)
        self.provider.sign_in_with_password.return_value = result()
        self.provider.get_user.return_value = result()
        self.provider.refresh_session.return_value = result()
        self.provider.set_session.return_value = result()
        self.provider.update_user.return_value = result()
        self.auth_patch = patch.object(web_api, "auth_client", return_value=types.SimpleNamespace(auth=self.provider))
        self.config_patch = patch.object(web_api, "signup_settings", return_value=True)
        self.auth_patch.start(); self.config_patch.start()

    def tearDown(self):
        self.auth_patch.stop(); self.config_patch.stop(); self.client.close()

    def post(self, name, data, origin=ORIGIN):
        return self.client.post("/api/auth/"+name, json=data, headers={"Origin":origin})

    def signup_data(self):
        return {"email":" Person@Example.org ", "username":" Researcher ", "password":PASSWORD,
                "role":"admin", "data":{"role":"admin"}}

    def cookies(self):
        self.client.cookies.set("mkh_access", "old-access")
        self.client.cookies.set("mkh_refresh", "old-refresh")

    def test_signup_sends_only_profile_name_and_never_establishes_session(self):
        response = self.post("signup", self.signup_data())
        self.assertEqual(response.status_code, 200)
        self.provider.sign_up.assert_called_once_with({"email":"person@example.org", "password":PASSWORD,
            "options":{"data":{"username":"Researcher"},"email_redirect_to":ORIGIN+"/"}})
        self.assertNotIn("set-cookie", response.headers)
        self.assertNotIn("user", response.json())

    def test_unverified_and_duplicate_signup_have_same_public_response(self):
        normal = self.post("signup", self.signup_data())
        self.provider.sign_up.side_effect = AuthApiError("private account detail", 422, "user_already_exists")
        duplicate = self.post("signup", self.signup_data())
        self.assertEqual(normal.json(), duplicate.json())
        self.assertEqual(duplicate.status_code, 200)
        self.assertNotIn("set-cookie", duplicate.headers)

    def test_provider_configuration_failure_blocks_creation(self):
        with patch.object(web_api,"signup_settings", return_value=False):
            self.assertEqual(self.post("signup", self.signup_data()).status_code, 503)
        self.provider.sign_up.assert_not_called()

    def test_unexpected_autoconfirm_session_is_rejected(self):
        self.provider.sign_up.return_value = result()
        response = self.post("signup", self.signup_data())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("set-cookie",response.headers)

    def test_signup_input_validation_before_provider(self):
        for change in [{"email":12}, {"email":"bad"}, {"username":"x"},
                       {"username":"name\nadmin"}, {"password":"short"}, {"password":"x"*257}]:
            with self.subTest(change=change):
                self.assertEqual(self.post("signup", self.signup_data() | change).status_code, 400)
        self.provider.sign_up.assert_not_called()

    def test_verified_login_returns_display_profile_and_secure_private_cookies(self):
        response = self.post("login", {"email":"Person@Example.org", "password":PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"], {"id":"existing-id", "email":"person@example.org", "username":"Researcher"})
        self.assertNotIn("role", response.json()["user"])
        self.provider.sign_in_with_password.assert_called_once_with({"email":"person@example.org","password":PASSWORD})
        for cookie in response.headers.get_list("set-cookie"):
            for flag in ["HttpOnly", "Secure", "SameSite=lax", "Path=/"]: self.assertIn(flag,cookie)
        self.assertEqual(response.headers["cache-control"],"no-store")
        self.assertNotIn(PASSWORD,response.text)

    def test_legacy_short_password_still_passed_to_provider(self):
        self.assertEqual(self.post("login", {"email":"person@example.org","password":"oldpass"}).status_code,200)

    def test_unverified_login_never_sets_cookies(self):
        self.provider.sign_in_with_password.return_value = result(user(confirmed=False))
        response=self.post("login", {"email":"person@example.org","password":PASSWORD})
        self.assertEqual(response.status_code,401);self.assertNotIn("set-cookie",response.headers)

    def test_wrong_password_and_unverified_errors_are_generic(self):
        responses=[]
        for code in ["invalid_credentials","email_not_confirmed"]:
            self.provider.sign_in_with_password.side_effect=AuthApiError("secret upstream detail",400,code)
            response=self.post("login",{"email":"person@example.org","password":PASSWORD})
            self.assertEqual(response.status_code,401); responses.append(response.json())
            self.assertNotIn("secret",response.text)
        self.assertEqual(*responses)

    def test_rate_limit_is_reported_without_provider_details(self):
        self.provider.sign_in_with_password.side_effect=AuthApiError("email and token",429,"over_request_rate_limit")
        self.assertEqual(self.post("login",{"email":"person@example.org","password":PASSWORD}).status_code,429)

    def test_recovery_uses_same_account_and_configured_redirect(self):
        response=self.post("recover",{"email":"Person@Example.org"})
        self.assertEqual(response.status_code,200)
        self.provider.reset_password_for_email.assert_called_once_with("person@example.org",{"redirect_to":ORIGIN+"/"})
        self.assertNotIn("set-cookie",response.headers)
        self.provider.sign_up.assert_not_called()

    def test_reset_requires_verified_session(self):
        self.assertEqual(self.post("password",{"password":PASSWORD}).status_code,401)
        self.cookies();self.provider.get_user.return_value=result(user(confirmed=False))
        self.provider.refresh_session.return_value=result(user(confirmed=False))
        self.assertEqual(self.post("password",{"password":PASSWORD}).status_code,401)
        self.provider.update_user.assert_not_called()

    def test_existing_account_password_update_preserves_uuid_and_metadata(self):
        self.cookies()
        response=self.post("password",{"password":PASSWORD,"username":"overwrite","role":"admin"})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["user"]["id"],"existing-id")
        self.provider.update_user.assert_called_once_with({"password":PASSWORD})
        self.provider.sign_up.assert_not_called()

    def test_expired_session_update_uses_rotated_refresh_token(self):
        self.cookies();self.provider.get_user.side_effect=Exception("expired")
        self.assertEqual(self.post("password",{"password":PASSWORD}).status_code,200)
        self.provider.set_session.assert_called_once_with("new-access","new-refresh")

    def test_mismatched_session_blocks_password_update(self):
        self.cookies();self.provider.set_session.return_value=result(user("other-id"))
        self.assertEqual(self.post("password",{"password":PASSWORD}).status_code,503)
        self.provider.update_user.assert_not_called()

    def test_verified_callback_rotates_and_checks_both_token_identities(self):
        response=self.post("session",{"access_token":"callback-access","refresh_token":"callback-refresh"})
        self.assertEqual(response.status_code,200)
        self.provider.get_user.assert_called_once_with("callback-access")
        self.provider.refresh_session.assert_called_once_with("callback-refresh")
        self.assertIn("new-refresh",response.headers.get_list("set-cookie")[1])

    def test_expired_empty_unverified_or_mismatched_callback_is_rejected(self):
        self.assertEqual(self.post("session",{"access_token":"","refresh_token":""}).status_code,400)
        self.provider.get_user.return_value=result(user(confirmed=False))
        self.assertEqual(self.post("session",{"access_token":"access","refresh_token":"refresh"}).status_code,401)
        self.provider.get_user.return_value=result()
        self.provider.refresh_session.return_value=result(user("different-account"))
        self.assertEqual(self.post("session",{"access_token":"access","refresh_token":"refresh"}).status_code,401)
        self.provider.get_user.side_effect=Exception("expired token secret")
        self.assertEqual(self.post("session",{"access_token":"access","refresh_token":"refresh"}).status_code,401)

    def test_legacy_email_link_cannot_create_new_accounts(self):
        self.assertEqual(self.post("email",{"email":"person@example.org"}).status_code,200)
        self.assertFalse(self.provider.sign_in_with_otp.call_args.args[0]["options"]["should_create_user"])

    def test_logout_revokes_current_session_and_always_clears_cookies(self):
        self.cookies()
        self.assertEqual(self.post("logout",{}).status_code,200)
        self.provider.sign_out.assert_called_once_with({"scope":"local"})
        self.provider.set_session.side_effect=Exception("offline")
        response=self.post("logout",{})
        self.assertEqual(response.status_code,200)
        self.assertTrue(all("Max-Age=0" in c for c in response.headers.get_list("set-cookie")))

    def test_all_auth_mutations_reject_cross_origin_and_wrong_body(self):
        for name in ["signup","login","recover","password","session","email","logout"]:
            with self.subTest(name=name):
                self.assertEqual(self.post(name,self.signup_data(),"https://attacker.example").status_code,403)
                self.assertEqual(self.client.post("/api/auth/"+name,content="wrong",headers={"Origin":ORIGIN}).status_code,403)
        self.provider.sign_up.assert_not_called();self.provider.sign_in_with_password.assert_not_called()

    def test_actor_refresh_does_not_admit_unverified_accounts(self):
        self.cookies();self.provider.get_user.return_value=result(user(confirmed=False))
        self.provider.refresh_session.return_value=result(user(confirmed=False))
        self.assertIsNone(self.client.get("/api/me").json()["user"])
        self.assertEqual(self.client.get("/api/conversations").status_code,401)

    def test_status_exposes_only_configuration_booleans(self):
        self.assertEqual(self.client.get("/api/auth/status").json(),
                         {"signup_enabled":True,"email_confirmation_required":True})

    def test_existing_saved_research_owner_is_preserved_after_password_login(self):
        from test_web_api import MemoryStore
        MemoryStore.accounts={}
        cid="00000000-0000-0000-0000-000000000001"
        MemoryStore("existing-id").create_conversation(cid,"Existing research","quick")
        with patch.object(web_api,"store_for",side_effect=lambda u,t:MemoryStore(u.id)):
            self.assertEqual(self.post("login",{"email":"person@example.org","password":PASSWORD}).status_code,200)
            self.assertEqual(self.client.get("/api/conversations").json()["conversations"][0]["id"],cid)
            self.assertEqual(self.client.get("/api/conversations/"+cid).status_code,200)
            self.provider.get_user.return_value=result(user("other-account"))
            self.assertEqual(self.client.get("/api/conversations/"+cid).status_code,404)
            self.assertEqual(len(MemoryStore.accounts["existing-id"]),1)

    def test_weak_password_response_does_not_echo_provider_content(self):
        self.provider.sign_up.side_effect=AuthApiError("private password content",422,"weak_password")
        response=self.post("signup",self.signup_data())
        self.assertEqual(response.status_code,400);self.assertNotIn("private",response.text)


class SignupConfigurationTests(unittest.TestCase):
    def test_public_settings_fail_closed_for_missing_or_disabled_confirmation(self):
        good={"mailer_autoconfirm":False,"disable_signup":False,"external":{"email":True}}
        with patch.dict("os.environ",{"SUPABASE_URL":"https://project.supabase.co", "SUPABASE_PUBLISHABLE_KEY":"test-public-key"}), \
             patch.object(web_api.requests,"get") as get:
            response=get.return_value
            for config,expected in [(good,True),(good|{"mailer_autoconfirm":True},False),
                                    (good|{"disable_signup":True},False),({},False),
                                    (good|{"external":{"email":False}},False)]:
                response.json.return_value=config
                self.assertEqual(web_api.signup_settings(),expected)
            get.assert_called_with("https://project.supabase.co/auth/v1/settings",
                                   headers={"apikey":"test-public-key"},timeout=10)


if __name__ == "__main__": unittest.main()
