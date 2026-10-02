"""Validated PDF ingestion. Dry-run by default; --commit writes only after validation.

Usage: python ingest.py file.pdf metadata.json [--commit]
Metadata uses the existing documents columns, including title, organization,
document_type, version, status, publication_date and source_url where known.
"""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

import fitz


def prepare(pdf_path, min_readable_ratio=0.80, max_chunk_chars=2200):
    raw = Path(pdf_path).read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise ValueError("File is not a PDF")
    document = fitz.open(stream=raw, filetype="pdf")
    if not document.page_count:
        raise ValueError("PDF has no pages")
    chunks, low_text_pages = [], []
    for page_number, page in enumerate(document, 1):
        text = page.get_text("text").replace("\x00", "").replace("\u00ad", "")
        text = re.sub(r"[ \t]+", " ", text).strip()
        if len(text) < 100:
            low_text_pages.append(page_number)
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        buffer = ""
        for paragraph in paragraphs:
            while len(paragraph) > max_chunk_chars:
                prefix = paragraph[:max_chunk_chars]
                split = max(prefix.rfind(". "), prefix.rfind("; "), prefix.rfind(" "))
                split = split + 1 if split > max_chunk_chars // 2 else max_chunk_chars
                if buffer:
                    chunks.append((page_number, buffer))
                    buffer = ""
                chunks.append((page_number, paragraph[:split].strip()))
                paragraph = paragraph[split:].strip()
            if len(buffer) + len(paragraph) + 2 > max_chunk_chars:
                chunks.append((page_number, buffer))
                buffer = ""
            buffer = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if buffer:
            chunks.append((page_number, buffer))
    summary = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "pages": document.page_count,
        "readable_pages": document.page_count - len(low_text_pages),
        "low_text_pages": low_text_pages,
        "chunks": len(chunks),
    }
    document.close()
    if summary["readable_pages"] / summary["pages"] < min_readable_ratio:
        raise ValueError(f"PDF extraction quality too low: {summary}; OCR required")
    if not chunks:
        raise ValueError("No usable text chunks")
    return chunks, summary


def commit(chunks, metadata):
    from openai import OpenAI
    from supabase import create_client

    required = ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "OPENAI_API_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    # Prepare every embedding before creating any database record.
    embeddings = []
    for start in range(0, len(chunks), 50):
        batch = chunks[start:start + 50]
        inputs = [f"Document: {metadata['title']}\nSection: Unknown\nPage: {page}\n\n{text}"
                  for page, text in batch]
        response = openai.embeddings.create(model="text-embedding-3-small", input=inputs)
        embeddings.extend(item.embedding for item in response.data)
    doc_id = client.table("documents").insert(metadata).execute().data[0]["id"]
    try:
        for start in range(0, len(chunks), 50):
            records = [{"document_id": doc_id, "page_number": page,
                        "chunk_index": i, "section_title": None, "content": content,
                        "embedding": embeddings[i]}
                       for i, (page, content) in enumerate(chunks)
                       if start <= i < start + 50]
            client.table("chunks").insert(records).execute()
    except Exception:
        client.table("documents").delete().eq("id", doc_id).execute()
        raise
    return doc_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text())
    if not metadata.get("title") or metadata.get("status") != "active":
        raise ValueError("Metadata needs title and explicit active status")
    chunks, summary = prepare(args.pdf)
    print(json.dumps(summary))
    if args.commit:
        print("created_document_id", commit(chunks, metadata))
    else:
        print("Dry-run completed; database unchanged")


if __name__ == "__main__":
    main()
