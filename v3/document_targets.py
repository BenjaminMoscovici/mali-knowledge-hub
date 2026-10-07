"""Find individually named government documents for balanced retrieval."""

import re
import unicodedata


def normal(text):
    value = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(c for c in value if not unicodedata.combining(c))


def named_targets(question, documents):
    q = normal(question)
    requested = set()
    if re.search(r"\b(?:vision mali 2063|mali kura 2063)\b", q):
        requested.add("vision")
    if "snedd" in q:
        requested.add("snedd")
    if re.search(r"\b(?:phasage|phasing|implementation phases?)\b", q):
        requested.add("phasage")
    elif re.search(r"\b(?:priority.project portfolio|priority projects|projets structurants prioritaires)\b", q):
        requested.add("portfolio")
    if len(requested) < 2:
        return []

    def kind(title):
        title = normal(title)
        if title.startswith("vision mali 2063"):
            return "vision"
        if title.startswith("strategie nationale pour"):
            return "snedd"
        if title.startswith("phasage"):
            return "phasage"
        if title.startswith("projets structurants prioritaires"):
            return "portfolio"
        return None

    matches = [(str(doc["id"]), doc["title"]) for doc in documents
               if kind(doc.get("title")) in requested]
    return matches if len(matches) == len(requested) else []


def explicit_title_targets(question, documents):
    """Find documents whose distinctive four-word title phrase was asked for."""
    question_words = re.findall(r"[a-z0-9]+", normal(question))
    question_fourgrams = {tuple(question_words[i:i + 4])
                          for i in range(max(0, len(question_words) - 3))}
    matches = []
    for doc in documents:
        title = doc.get("title") or ""
        words = re.findall(r"[a-z0-9]+", normal(title))
        if len(words) < 4:
            continue
        if any(tuple(words[i:i + 4]) in question_fourgrams
               for i in range(len(words) - 3)):
            matches.append((str(doc["id"]), title))
    return matches


def response_report_targets(question, documents):
    """Bound annex lookups to catalogue reports of an explicitly named publisher."""
    from synthesis_context import response_coverage_workflow
    if not response_coverage_workflow(question):
        return []
    q=normal(question)
    matches=[]
    for doc in documents:
        organization=str(doc.get('organization') or '').strip()
        labels={normal(organization)}
        labels.update(normal(alias) for alias in re.findall(r'\(([A-Za-z][A-Za-z0-9_-]{1,12})\)',organization))
        named=any(len(label)>=3 and re.search(r'(?<!\w)'+re.escape(label)+r'(?!\w)',q) for label in labels)
        report=bool(re.search(r'\b(report|rapport)\b',normal(str(doc.get('title') or '')+' '+str(doc.get('document_type') or ''))))
        if named and report and doc.get('id'):
            matches.append((str(doc['id']),str(doc.get('title') or 'Report')))
    # A large or ambiguous publisher collection needs a narrower research scope.
    return list(dict.fromkeys(matches)) if len(matches)<=3 else []
