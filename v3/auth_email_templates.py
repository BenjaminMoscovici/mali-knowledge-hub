"""Build secret-free Supabase email-branding settings; never sends or applies them."""
import argparse
from html import escape
import json
from pathlib import Path

BRAND = "Mali Knowledge Hub"
CONFIRMATION_URL = "{{ .ConfirmationURL }}"
MESSAGES = {
    "confirmation": {
        "subject": "Confirm your Mali Knowledge Hub account",
        "title": "Confirm your email address",
        "body": "You requested an account for Mali Knowledge Hub. Confirm your email address to finish setting it up.",
        "action": "Confirm my email address",
        "next": "After confirmation, the Hub will show that your account is ready. Next time, sign in with your email address and personal password.",
    },
    "recovery": {
        "subject": "Reset your Mali Knowledge Hub password",
        "title": "Choose a new password",
        "body": "A password reset was requested for your Mali Knowledge Hub account. Use the button below to choose a new password.",
        "action": "Reset my password",
        "next": "Your account and saved research stay the same. If you did not request this reset, ignore this email; your password will not change.",
    },
    "magic_link": {
        "subject": "Your Mali Knowledge Hub sign-in link",
        "title": "Sign in to your account",
        "body": "Use this one-time link to sign in to your existing Mali Knowledge Hub account.",
        "action": "Sign in to Mali Knowledge Hub",
        "next": "If you did not request this sign-in link, ignore this email. Do not forward the link to anyone else.",
    },
}


def template(kind):
    message = {key: escape(value) for key, value in MESSAGES[kind].items()}
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{message["subject"]}</title></head>
<body style="margin:0;padding:32px 12px;background:#f5f7f5;color:#26332e;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" style="width:100%;max-width:560px;margin:0 auto;border-collapse:collapse;background:#fff;border:1px solid #dfe7e2;border-radius:12px;">
<tr><td style="padding:30px 30px 18px;"><span style="display:inline-block;padding:10px 14px;background:#28786e;color:white;border-radius:10px;font-size:20px;font-weight:bold;">M</span><p style="margin:14px 0 0;font-size:14px;font-weight:bold;color:#28786e;">{BRAND}</p></td></tr>
<tr><td style="padding:0 30px 30px;"><h1 style="font-size:25px;line-height:1.3;margin:0 0 18px;">{message["title"]}</h1>
<p style="font-size:15px;line-height:1.65;margin:0 0 22px;">{message["body"]}</p>
<table role="presentation" style="border-collapse:collapse;"><tr><td style="background:#28786e;border-radius:8px;"><a href="{CONFIRMATION_URL}" style="display:inline-block;padding:14px 20px;color:#fff;text-decoration:none;font-size:14px;font-weight:bold;">{message["action"]}</a></td></tr></table>
<p style="font-size:13px;line-height:1.65;margin:24px 0 0;color:#64716a;">{message["next"]}</p>
<p style="font-size:12px;line-height:1.6;margin:18px 0 0;color:#64716a;">If you did not request this email, you can safely ignore it. Mali Knowledge Hub will never ask you to send your password by email.</p>
</td></tr></table></body></html>'''


def management_patch(*, include_sender_name=False):
    """Only email subjects/content; sender name is explicitly opt-in after SMTP verification."""
    patch = {}
    for kind, message in MESSAGES.items():
        patch[f"mailer_subjects_{kind}"] = message["subject"]
        patch[f"mailer_templates_{kind}_content"] = template(kind)
    if include_sender_name:
        patch["smtp_sender_name"] = BRAND
    return patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write the provider configuration patch JSON")
    parser.add_argument("--preview-dir", type=Path, help="Write nonfunctional email previews")
    parser.add_argument("--include-sender-name", action="store_true",
                        help="Include sender display name only after verifying a custom SMTP sender")
    args = parser.parse_args()
    if not args.output and not args.preview_dir:
        parser.error("Choose --output and/or --preview-dir; no remote settings are changed.")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(management_patch(include_sender_name=args.include_sender_name),
                                         ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.preview_dir:
        args.preview_dir.mkdir(parents=True, exist_ok=True)
        for kind in MESSAGES:
            preview = template(kind).replace(CONFIRMATION_URL, "https://example.invalid/preview-only")
            (args.preview_dir / f"{kind}.html").write_text(preview, encoding="utf-8")


if __name__ == "__main__":
    main()
