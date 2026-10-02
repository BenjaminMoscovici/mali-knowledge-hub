"""Read-only corpus metadata audit; no source text is sent onward."""

import getpass
import json
import os
import urllib.request


def get(path, key):
    base = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
    req = urllib.request.Request(base + path, headers={
        "apikey": key, "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def main():
    key = getpass.getpass("MKH Supabase secret key (hidden): ")
    docs = get("/documents?select=*&order=title.asc", key)
    for doc in docs:
        print(json.dumps({"title": doc.get("title"),
                          "organization": doc.get("organization"),
                          "document_type": doc.get("document_type"),
                          "status": doc.get("status"),
                          "fields": sorted(doc.keys()),
                          "source_fields": {k: v for k, v in doc.items()
                                            if "source" in k or "url" in k or
                                            "license" in k or "access" in k}},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
