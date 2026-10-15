"""A conservative French/English output-language selector for benchmark queries."""

import re


def answer_language(question):
    q = (question or "").strip().casefold()
    french_openings = r"^(?:quels?\b|quelles?\b|que\b|qu['’]|combien\b|comment\b|pourquoi\b|où\b|est-ce\b|peut-on\b|dans quelle?\b|comparez\b|vérifiez\b|lesquels?\b|les\b|le\b|la\b|des\b|ces\b|et\b|mais\b|même\b|à\b|pour\b|pouvez-vous\b|peux-tu\b|cela\b|cette\b)"
    return "French" if re.search(french_openings, q) else "English"


def synthesis_language(question):
    """Recognise clear German requests without changing deterministic EN/FR routes."""
    q = (question or '').strip().casefold()
    german = r"^(?:welch(?:e|er|es|en|em)|wie|wieso|weshalb|warum|wo|wann|wer|wieviel(?:e)?|kannst|können|gibt|erklär(?:e)?|zeig(?:e)?|bitte|und|aber|was(?=\s+(?:ist|sind|bedeutet|kann|lässt|sagt|wissen|zeigt|war)))\b"
    return 'German' if re.search(german, q) else answer_language(question)
