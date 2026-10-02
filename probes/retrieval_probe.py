"""One-question, read-only retrieval probe against the frozen v0.3 backend."""

import getpass
import json
import os
import time
import urllib.error
import urllib.request

QUESTION = "Quels sont les grands axes de la SNEDD 2024–2033 ?"


def json_request(url, payload, headers):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        **headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read(2048).decode("utf-8", "replace")}


def main():
    openai_key = getpass.getpass("OpenAI key (hidden): ")
    supabase_key = getpass.getpass("Supabase key (hidden): ")
    started = time.perf_counter()
    status, embedding = json_request(
        "https://api.openai.com/v1/embeddings",
        {"model": "text-embedding-3-small", "input": QUESTION},
        {"Authorization": f"Bearer {openai_key}"})
    print(json.dumps({"stage": "embedding", "status": status,
                      "seconds": round(time.perf_counter() - started, 2),
                      "usage": embedding.get("usage"),
                      "error": embedding.get("error") if status != 200 else None},
                     ensure_ascii=False))
    if status != 200:
        return
    vector = embedding["data"][0]["embedding"]
    started = time.perf_counter()
    status, results = json_request(
        os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/match_chunks",
        {"query_embedding": vector, "match_count": 12,
         "filter_document_ids": None},
        {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"})
    print(json.dumps({"stage": "match_chunks", "status": status,
                      "seconds": round(time.perf_counter() - started, 2),
                      "returned": len(results) if isinstance(results, list) else None,
                      "hits": [{"document_id": r.get("document_id"),
                                "page_number": r.get("page_number"),
                                "similarity": r.get("similarity")}
                               for r in results] if isinstance(results, list) else [],
                      "error": results.get("error") if isinstance(results, dict) else None},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
