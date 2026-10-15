# Mali Knowledge Hub account emails

The app has clear account creation, email verification and verified-account completion screens. The confirmation screen shows the entered address and supports explicit resend, a corrected address, sign-in and password recovery. Successful signup confirmation shows the verified account email and a persistent “Your account is ready” screen.

Branded confirmation, password recovery and existing-account sign-in email subjects/content are prepared in `v3/auth_email_templates.py`. These templates use the provider's `{{ .ConfirmationURL }}` unchanged, so the selected redirect and expiry stay under the authentication provider's control. There is no user metadata, tracking image or third-party resource in an email.

This repository deployment alone does **not** apply hosted email templates or change the From identity. To prepare the exact content-only patch without credentials or network requests:

```sh
python v3/auth_email_templates.py --output /tmp/mkh-email-content.json --preview-dir /tmp/mkh-email-preview
```

In the correct Supabase project's authenticated dashboard, preserve a snapshot of the existing email subjects/content and SMTP settings before editing. Apply only the three prepared subjects/content through Authentication → Email templates. Preserve all other templates, email confirmation, redirect allowlists, authentication providers, rate limits and sender credentials. Apply no invitations or account changes as part of branding.

For the actual From display name, use **Mali Knowledge Hub**. Configure it against an existing approved custom SMTP sender. An approved sender address/domain and the corresponding email-service setup are required; do not use an administrator's personal or work address as a sending identity merely because it is an admin account. Do not invent an address, add a new mail service, change billing or replace a working sender without the owner's choice.

After verifying an existing custom SMTP sender, `--include-sender-name` adds only `smtp_sender_name` to the prepared patch. It does not set an address, enable custom SMTP or supply credentials. A content-only change cannot turn Supabase's default From identity into a Hub-owned sender. If the email provider rewrites links through tracking, turn off link tracking for these authentication messages using the provider's supported setting.

Acceptance requires an authorized mailbox to confirm the visible sender name/address, subject/content, real link destination, completed verification screen, password login, resend/expiry and password recovery. Users enter their own passwords; never capture real confirmation URLs, tokens or credentials in public receipts or repository files. Preview links are deliberately nonfunctional.

The existing administration service uses its server-side `MKH_ADMIN_EMAILS` allowlist. Public signup and username metadata do not change admin access. Invitation-based administration and its own-password onboarding remain separately tracked in Q-032.

Provider references: [email templates](https://supabase.com/docs/guides/auth/auth-email-templates), [custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp).
