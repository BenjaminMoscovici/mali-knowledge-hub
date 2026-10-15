"""Guard provider link behavior and the narrow, secret-free branding patch."""
from html.parser import HTMLParser
from auth_email_templates import BRAND, CONFIRMATION_URL, MESSAGES, management_patch, template


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.hrefs = []; self.scripts = []
    def handle_starttag(self, tag, attrs):
        if tag == "a": self.hrefs.append(dict(attrs).get("href"))
        if tag in {"script", "iframe", "img"}: self.scripts.append(tag)


def test_branded_email_templates_keep_provider_confirmation_link_and_no_tracking():
    for kind in MESSAGES:
        html=template(kind); parser=Links(); parser.feed(html)
        assert BRAND in html and MESSAGES[kind]["subject"] in html
        assert parser.hrefs == [CONFIRMATION_URL]
        assert not parser.scripts
        assert ".Data" not in html and ".Email" not in html
        assert "password by email" in html


def test_template_patch_cannot_disable_verification_or_replace_sender_credentials():
    patch=management_patch()
    assert set(patch) == {f"mailer_subjects_{kind}" for kind in MESSAGES} | {
        f"mailer_templates_{kind}_content" for kind in MESSAGES}
    assert management_patch(include_sender_name=True) == patch | {"smtp_sender_name": BRAND}
