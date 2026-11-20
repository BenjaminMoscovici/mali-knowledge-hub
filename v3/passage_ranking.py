"""Preserve semantic candidates while rescuing exact matches from the same search."""

from collections import Counter
import re

from synthesis_context import fold, terms


def rerank_passages(rows, question, limit):
    """Reserve one slot for strong lexical evidence outside the semantic cutoff."""
    primary = rows[:limit]
    if limit < 2 or len(rows) <= limit:
        return primary

    text = fold(question)
    authored = set(re.findall(r"\b[a-z][a-z0-9]{3,}\b", text))
    keywords = terms(question) & authored
    identifiers = set(re.findall(r"\b(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]*\d)[a-z][a-z0-9-]{3,}\b", text))
    phrases = [fold(value) for value in re.findall(r'["“]([^"”]{4,80})["”]', question)]
    contents = [fold(row.get("content") or "") for row in rows]
    token_sets = [set(re.findall(r"\b[a-z0-9-]+\b", content)) for content in contents]
    frequencies = Counter(word for tokens in token_sets for word in tokens & keywords)
    rare = {word for word, count in frequencies.items() if count * 2 <= len(rows)}

    def strength(index):
        tokens = token_sets[index]
        exact = len(identifiers & tokens) + sum(
            bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", contents[index])) for phrase in phrases
        )
        return exact, len(tokens & rare)

    best = max(range(limit, len(rows)), key=strength)
    score = strength(best)
    if (not score[0] and score[1] < 2) or score <= max(map(strength, range(limit))):
        return primary
    return primary[:-1] + [{**rows[best], "lexical_rescue": True}]
