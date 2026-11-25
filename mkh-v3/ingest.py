"""Turn a reviewed public file or connection description into a versioned source proposal."""

import base64
import binascii
import csv
import hashlib
import io
import json
import math
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

from knowledge import KnowledgeError, SOURCE_ID, SQL_TYPES, https_url

MAX_FILE = 1500000
MAX_ROWS = 5000


def slug(value):
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def text_field(data, key, limit=350):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise KnowledgeError("Check the length or format of " + key + ".")
    return value.strip()


def table_data(matrix, name, overrides):
    try:
        headers = [str(h or "").strip() for h in next(matrix)]
    except StopIteration:
        raise KnowledgeError("The file contains no table.") from None
    if not 1 <= len(headers) <= 30 or not all(headers):
        raise KnowledgeError("Use a table with 1 to 30 named columns.")
    keys = []
    for n, heading in enumerate(headers):
        key = slug(heading)[:48] or "field_" + str(n + 1)
        if not key[0].isalpha() or key in {"id", "locator"}:
            key = "source_" + key
        if key in keys:
            raise KnowledgeError("Column names must remain distinct after normalization.")
        keys.append(key)
    if set(overrides) - set(keys) or any(t not in SQL_TYPES for t in overrides.values()):
        raise KnowledgeError("Column types must refer to a proposed column and use TEXT, INTEGER or REAL.")
    records = []
    for index, values in enumerate(matrix, 2):
        if index > MAX_ROWS + 1:
            raise KnowledgeError("This upload exceeds the 5,000-row integration limit.")
        if len(values) != len(keys):
            raise KnowledgeError(f"Row {index} has a different number of cells from the header.")
        cells = [None if v is None or str(v).strip() == "" else str(v).strip() for v in values]
        if any(isinstance(v, str) and len(v) > 10000 for v in cells):
            raise KnowledgeError("A table cell exceeds the supported length.")
        if any(v is not None for v in cells):
            records.append({"id": str(index), "locator": f"{name} / row {index}", **dict(zip(keys, cells))})
    if not records:
        raise KnowledgeError("The table has no observations.")
    columns = {"id": "TEXT", "locator": "TEXT"}
    dimensions = []
    for heading, key in zip(headers, keys):
        values = {r[key] for r in records if r[key] is not None}
        kind = overrides.get(key, "TEXT")
        if key not in overrides and values:
            if all(re.fullmatch(r"-?(0|[1-9][0-9]*)", v) for v in values):
                kind = "INTEGER" if all(len(v) < 19 for v in values) else "TEXT"
            elif all(re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", v) for v in values):
                kind = "REAL"
        columns[key] = kind
        if kind == "TEXT" and 1 < len(values) <= 32:
            dimensions.append(key)
        if kind != "TEXT":
            for row in records:
                if row[key] is None:
                    continue
                try:
                    value = int(row[key]) if kind == "INTEGER" else float(row[key])
                    if not math.isfinite(value) or (kind == "INTEGER" and not -(2**63) <= value < 2**63):
                        raise ValueError
                except (ValueError, OverflowError):
                    raise KnowledgeError("Some values cannot be stored as " + kind + " in " + heading) from None
                row[key] = value
    return {"type": "dataset", "table": "observations", "columns": columns, "dimensions": dimensions[:8],
            "records": records, "definitions": {key: label for key, label in zip(keys, headers)}}


def materialize(body):
    meta = body.get("metadata")
    if not isinstance(meta, dict):
        raise KnowledgeError("Missing source metadata.")
    filename = Path(text_field(body, "filename", 160)).name
    if not filename or not isinstance(body.get("content"), str):
        raise KnowledgeError("Choose a public source file.")
    try:
        raw = base64.b64decode(body["content"], validate=True)
    except (ValueError, binascii.Error):
        raise KnowledgeError("The source file could not be decoded.") from None
    if not 1 <= len(raw) <= MAX_FILE:
        raise KnowledgeError("Choose a nonempty file of at most 1.5 MB.")
    suffix, stream = Path(filename).suffix.lower(), io.BytesIO(raw)
    overrides = meta.get("column_types") or {}
    if not isinstance(overrides, dict):
        raise KnowledgeError("Column type overrides must be a JSON object.")
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        with zipfile.ZipFile(stream) as archive:
            if sum(i.file_size for i in archive.infolist()) > 18000000 or len(archive.infolist()) > 400:
                raise KnowledgeError("The workbook exceeds the extraction budget.")
        book = load_workbook(stream, read_only=True, data_only=True, keep_links=False)
        try:
            sheet = text_field(meta, "sheet", 120) or book.sheetnames[0]
            if sheet not in book.sheetnames:
                raise KnowledgeError("Choose a sheet from this workbook.")
            if (book[sheet].max_column or 0) > 30:
                raise KnowledgeError("Select a sheet with at most 30 columns.")
            result = table_data(iter(book[sheet].values), sheet, overrides)
            result["sheet"] = sheet
        finally:
            book.close()
    elif suffix in {".tsv", ".csv"}:
        text = raw.decode("utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel_tab if suffix == ".tsv" else csv.excel
        result = table_data(iter(csv.reader(io.StringIO(text, newline=""), dialect=dialect)), filename, overrides)
    elif suffix in {".pdf", ".txt", ".md"}:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(stream)
            if reader.is_encrypted or len(reader.pages) > 120:
                raise KnowledgeError("Use an unencrypted PDF with at most 120 pages.")
            pages = ((i, p.extract_text() or "") for i, p in enumerate(reader.pages, 1))
        else:
            pages = enumerate(raw.decode("utf-8-sig").split("\f"), 1)
        passages, used = [], 0
        for number, content in pages:
            if content.strip():
                used += len(content)
                if used > 400000:
                    raise KnowledgeError("The document exceeds the searchable text limit.")
                passage = {"kind": "source_passage", "locator": f"{filename} / page {number}", "text": content.strip()}
                if suffix == ".pdf":
                    passage["page"] = number
                passages.append(passage)
        if not passages:
            raise KnowledgeError("The document has no extractable text. Supply an accessible text version.")
        result = {"type": "document", "passages": passages}
    elif suffix == ".json":
        conf = json.loads(raw)
        if not isinstance(conf, dict) or conf.get("adapter") != "world_bank_wdi" or conf.get("country_code") != "MLI":
            raise KnowledgeError("Connection JSON supports the reviewed World Bank WDI adapter for Mali.")
        series = conf.get("series")
        if not isinstance(series, dict) or not 1 <= len(series) <= 60:
            raise KnowledgeError("Provide 1 to 60 indicator codes with labels and units.")
        cleaned = {}
        for code, spec in series.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_.]{1,79}", code) or not isinstance(spec, dict):
                raise KnowledgeError("Invalid WDI series description.")
            cleaned[code] = {k: text_field(spec, k) for k in ("label", "unit")}
            if not all(cleaned[code].values()):
                raise KnowledgeError("Every series needs a label and unit.")
        result = {"type": "live", "adapter": "world_bank_wdi", "country_code": "MLI", "series": cleaned}
    else:
        raise KnowledgeError("Use CSV, TSV, XLSX, PDF, text, Markdown or a supported connection JSON.")
    title = text_field(meta, "title", 200) or Path(filename).stem
    source_id = text_field(meta, "id", 90) or slug(title).replace("_", "-")[:86]
    if not SOURCE_ID.fullmatch(source_id):
        raise KnowledgeError("Use a source ID beginning with a letter, followed by lowercase letters, digits or hyphens.")
    manifest = {k: text_field(meta, k, 1500 if k == "description" else 350) for k in
                ("publisher", "url", "release", "period", "geography", "license", "description", "update_policy")}
    if len(manifest["release"]) > 140:
        raise KnowledgeError("Use a release identifier of at most 140 characters.")
    if manifest["url"] and not https_url(manifest["url"]):
        raise KnowledgeError("The original source URL must use HTTPS.")
    manifest.update(result, id=source_id, title=title, review="published", upload_sha256=hashlib.sha256(raw).hexdigest(),
                    original_filename=filename, topics=[t.strip() for t in text_field(meta,"topics",600).split(",") if t.strip()],
                    limitations=[v.strip() for v in text_field(meta,"limitations",1500).splitlines() if v.strip()])
    if body.get("operation") == "draft" and not all(manifest[k] for k in
            ("publisher","url","release","period","geography","license","description","limitations","update_policy")):
        raise KnowledgeError("Complete the provenance, coverage, licence, limitations and update policy before saving a draft.")
    if len(json.dumps(manifest, ensure_ascii=False).encode()) > 1350000:
        raise KnowledgeError("The extracted source exceeds the review limit. Submit a smaller release.")
    return manifest


if __name__ == "__main__":
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (384000000, 384000000))
    resource.setrlimit(resource.RLIMIT_CPU, (9, 10))
    try:
        print(json.dumps({"manifest": materialize(json.load(sys.stdin))}, allow_nan=False))
    except KnowledgeError as exc:
        print(json.dumps({"error": str(exc)}))
    except Exception:
        print(json.dumps({"error": "File extraction failed. Verify the file format and source contents."}))
