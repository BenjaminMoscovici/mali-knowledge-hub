"""Identify Markdown spans without changing the original answer layout."""

import re

EVIDENCE_ID = re.compile(r"\bE\d{2,}\b")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
BLOCK_START = re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|~~~)")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s)")
CITATION_ONLY = re.compile(r"^(?:\[E\d{2,}(?:\s*[,;]\s*E\d{2,})*\]\s*)+[.!?]?$")


def review_units(lines):
    """Map each review unit to the span it occupies in the rendered answer."""
    units = {}
    end = {}
    previous = None
    for index, line in enumerate(lines):
        text = line.strip()
        if not text:
            previous = None
            continue
        if previous is not None and not BLOCK_START.match(line):
            prior = units[previous]
            can_wrap = not BLOCK_START.match(prior) or (LIST_ITEM.match(prior) and line.startswith("  "))
            if can_wrap and (
                (CITATION_ONLY.fullmatch(text) and not EVIDENCE_ID.search(prior))
                or (not EVIDENCE_ID.search(prior) and not re.search(r"[.!?:][\"”']?$", prior))
            ):
                units[previous] += " " + text
                end[previous] = index + 1
                continue
        units[index] = line
        end[index] = index + 1
        previous = index
    return units, end


def table_cells(line):
    return re.split(r"(?<!\\)\|", line.strip().strip("|"))


def tables(lines):
    index = 0
    while index + 1 < len(lines):
        if not (lines[index].lstrip().startswith("|") and lines[index + 1].lstrip().startswith("|")):
            index += 1
            continue
        header, divider = table_cells(lines[index]), table_cells(lines[index + 1])
        if len(header) < 2 or len(header) != len(divider) or not all(
            re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in divider
        ):
            index += 1
            continue
        end = index + 2
        while end < len(lines) and lines[end].lstrip().startswith("|") and len(table_cells(lines[end])) == len(header):
            end += 1
        yield index, end
        index = end
