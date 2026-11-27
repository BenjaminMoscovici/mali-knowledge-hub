"""Build one versioned full-text component from a verified original and a whole-work rights receipt.

Build dependencies: PyMuPDF, lxml, Tesseract with the edition's language, plus runtime requirements.
Usage: python scripts/build_document.py MANIFEST ORIGINAL RIGHTS_JSON REUSE_EVIDENCE CANON_DIRECTORY OUTPUT_MANIFEST
"""
import argparse
import base64
from collections import Counter
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys

import fitz
from lxml import html
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from document_vectors import MODEL, encode
from retrieval import tokens

SCHEMA = 1
STOP = set("pour avec dans sont cette cela entre leurs notre ainsi comme aussi sans tous toutes chaque aux des les par sur ses qui que une est du the and for with from this that they have been such may its not shall will under article chapitre section titre page mali république republique ministre journal officiel".split())
LABEL = re.compile(r"^(livre|book|partie|part|titre|title|chapitre|chapter|section|sous-section|annexe|annex|article)\s+([\divxlcdm]+\b|premier|unique|\d+\s*er)", re.I)
LEVEL = dict(livre=1,book=1,partie=1,part=1,titre=2,title=2,chapitre=3,chapter=3,section=4,annexe=1,annex=1,article=6)
MAX_SECTION = 1800


def sha(data):
    return hashlib.sha256(data).hexdigest()


def keywords(text, n):
    return [t for t, _ in Counter(w for w in tokens(text) if len(w) > 3 and w not in STOP and w.isalpha()).most_common(n)]


def ocr(page, language):
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csGRAY, alpha=False)
    if (np.frombuffer(pix.samples, dtype="uint8") < 190).mean() < .00015:
        return []
    run = subprocess.run(["tesseract", "stdin", "stdout", "-l", language, "tsv"],
                         input=pix.tobytes("png"), capture_output=True, timeout=90, check=True)
    lines = {}
    scores = []
    for row in csv.DictReader(io.StringIO(run.stdout.decode()), delimiter="\t", quoting=csv.QUOTE_NONE):
        word = (row.get("text") or "").strip()
        if word:
            key = tuple(row[s] for s in ("block_num", "par_num", "line_num"))
            lines.setdefault(key, []).append(word)
            scores.append(float(row["conf"]))
    if not scores or np.median(scores) < 70:
        raise ValueError(f"Unresolved image/OCR on PDF page {page.number+1}")
    return [(" ".join(words), 0) for words in lines.values()]


def pdf_units(raw, language):
    with fitz.open(stream=raw, filetype="pdf") as doc:
        outline = {}
        for level, label, number in doc.get_toc():
            if number > 0:
                outline.setdefault(number, []).append((level, label))
        for page in doc:
            blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)["blocks"]
            lines = []
            sizes = []
            for block in blocks:
                for line in block.get("lines", []):
                    spans = line["spans"]
                    value = "".join(s["text"] for s in spans).strip()
                    if value:
                        size = max(s["size"] for s in spans)
                        lines.append((value, size))
                        sizes.append(size)
            method = "embedded text"
            body = " ".join(v for v,_ in lines)
            if (len(re.findall(r"[^\W\d_]",body)) < 25 and (page.get_images() or len(page.get_drawings()) > 30 or not body.strip())) or body.count("\ufffd") > max(3,len(body)*.01):
                candidate = ocr(page, language)
                if candidate:
                    lines, sizes, method = candidate, [], "OCR"
                elif not lines:
                    method = "blank"
            normal = float(np.median(sizes)) if sizes else 0
            yield page.number + 1, "", lines, normal, outline.get(page.number + 1, []), method


def html_units(raw, body_xpath=None):
    root = html.fromstring(raw)
    found = root.xpath('//main|//*[@role="main"]')
    if not found:
        found = root.xpath('//article')
    if body_xpath:
        found = root.xpath(body_xpath)
    if len(found) != 1:
        raise ValueError("No unique published HTML body")
    body = found[0]
    for tag in body.xpath('.//script|.//style|.//nav|.//aside|.//footer|.//input|.//button|.//select|.//textarea|.//noscript|.//*[@hidden]'):
        tag.drop_tree()
    # Assign every text node once, including prose in generic containers.
    lines = []
    for node in body.xpath('.//text()'):
        value = " ".join(str(node).split())
        if not value:
            continue
        parent = node.getparent()
        if node.is_tail:
            parent = parent.getparent()
        owner = next((x for x in [parent,*parent.iterancestors()] if x.tag in
                      ("h1","h2","h3","h4","h5","h6","p","li","tr","div","main","article")), body)
        if lines and lines[-1][0] is owner:
            lines[-1][1] += " " + value
        else:
            lines.append([owner,value])
    anchor = ""
    group = []
    for node, value in lines:
        level = int(node.tag[1]) if re.fullmatch(r"h[1-6]",node.tag) else 0
        if level:
            if group:
                yield None,anchor,group,0,[],"HTML"
            anchor = node.get("id","")
            group = []
        group.append((value,-level))
    if group:
        yield None,anchor,group,0,[],"HTML"


def build(source, raw, rights, terms):
    if (source["type"] != "document" or rights.get("scope") != "whole_work" or
        not rights.get("basis") or rights["source_id"] != source["id"] or
        rights["upstream_sha256"] != source["upstream_checksum"] or sha(raw) != source["upstream_checksum"] or
        rights["reuse_url"] != source["reuse_url"] or rights["reuse_sha256"] != sha(terms)):
        raise ValueError("A matching original, whole-work permission and terms receipt are required")
    pdf = raw.startswith(b"%PDF")
    sections, hierarchy, methods = [], {}, []
    def heading(level, name):
        for old in list(hierarchy):
            if old >= level: del hierarchy[old]
        hierarchy[level] = name[:180]
    units = pdf_units(raw, rights.get("ocr_language","fra")) if pdf else html_units(raw, rights.get("body_xpath"))
    for number, anchor, lines, normal, bookmarks, method in units:
        methods.append(method)
        if bookmarks:
            # PDF outlines provide structural context, never substitute them for page text.
            for level,name in bookmarks: heading(level,name)
        buf = []
        def flush():
            if not buf:return
            text = "\n".join(buf);buf.clear()
            while text:
                end = min(len(text), MAX_SECTION)
                if end < len(text):
                    split = max(text.rfind("\n",end//2,end),text.rfind(" ",end//2,end))
                    if split >= 0:end=split+1
                part,text=text[:end],text[end:]
                loc = ("PDF p. "+str(number) if pdf else "HTML") + " · §" + str(len(sections)+1)
                sections.append(dict(locator=loc,page=number,anchor=anchor,path=list(hierarchy.values()),
                                     text=part,kind="original_passage",method=method))
        for line, size in lines:
            label=LABEL.match(line)
            level = -size if size<0 else LEVEL.get(label[1].lower(),5) if label else 0
            if not level and normal and len(line)<110 and size>normal*1.23:
                level=4
            if level:
                flush();heading(level,line.split(" : ",1)[0] if label and label[1].lower()=="article" else line)
            buf.append(line)
        flush()
    if not sections:raise ValueError("The original contained no searchable text")
    for s in sections:
        s["topics"]=keywords(s["text"],5)
        vector=encode(" / ".join(s["path"][-2:])+"\n"+s["text"])
        s["embedding"]=base64.b64encode(vector.astype("<f2").tobytes()).decode()
    metadata = {"title": source["title"], "publisher": source["publisher"], "period": source["period"]}
    if pdf:
        with fitz.open(stream=raw,filetype="pdf") as original:
            for key in ("title","subject","keywords","creationDate"):
                value=(original.metadata or {}).get(key)
                if value:metadata["pdf_"+key]=value[:320]
    return dict(metadata=metadata,schema=SCHEMA,model=MODEL,upstream_sha256=sha(raw),format="PDF" if pdf else "HTML",
                pages=len(methods) if pdf else None,ocr_pages=methods.count("OCR"),blank_pages=methods.count("blank"),
                keywords=keywords(" ".join(s["text"] for s in sections),18),passages=sections)


def publishable(source, package, rights, canon):
    payload=json.dumps(package,ensure_ascii=False,separators=(",",":")).encode()
    packed=gzip.compress(payload,compresslevel=7,mtime=0);digest=sha(packed)
    folder=canon/"documents";folder.mkdir(parents=True,exist_ok=True)
    file=folder/(digest+".json.gz")
    if not file.exists():
        import tempfile, os
        with tempfile.NamedTemporaryFile(dir=folder,delete=False) as f:
            f.write(packed)
        os.replace(f.name,file)
    elif sha(file.read_bytes())!=digest:raise ValueError("Existing package differs from digest")
    preview={k:package[k] for k in ("format","pages","ocr_pages","blank_pages","keywords","model","upstream_sha256","metadata")}
    result=dict(source)
    result["document_snapshot"]=dict(**preview,sha256=digest,sections=len(package["passages"]),rights=rights)
    result["release"]=source["release"][:110]+" · full text "+digest[:12]
    result["license"]=rights["basis"]
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("manifest","original","rights","terms","canon","output"):
        parser.add_argument(name,type=Path)
    a=parser.parse_args()
    source=json.loads(a.manifest.read_text()); rights=json.loads(a.rights.read_text())
    package=build(source,a.original.read_bytes(),rights,a.terms.read_bytes())
    a.output.write_text(json.dumps(publishable(source,package,rights,a.canon),ensure_ascii=False,indent=2)+"\n")
