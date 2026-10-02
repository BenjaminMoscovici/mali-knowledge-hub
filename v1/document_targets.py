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
