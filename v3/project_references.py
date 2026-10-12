"""Source-qualified lookup identifiers, never evidence copied from a conversation."""
import re
import unicodedata


def fongim_project_ids(question, limit=20, preserve_order=False):
    q = ''.join(c for c in unicodedata.normalize('NFKD', question.casefold())
                if not unicodedata.combining(c))
    if not re.search(r'\bfongim\b', q):
        return ()
    ids = []
    seen = set()
    label = r'(?:fongim\s+(?:project\s+|projet\s+)?(?:ids?|identifiants?)|project\s+ids?|projet\s+(?:ids?|identifiants?)|identifiants?\s+(?:des?\s+)?projets?|ids?)'
    # Require an explicit ID label. Years, budgets and unqualified numbers
    # must not be turned into project identities. Match complete integers.
    for match in re.finditer(r'\b' + label + r'\s*[:#]?\s+(\d+(?:(?:\s*,\s*(?:(?:and|et)\s+)?|\s+(?:and|et)\s+)\d+)*)\b(?![-\w])', q):
        for value in map(int, re.findall(r'\d+', match.group(1))):
            if value > 0 and value not in seen:
                ids.append(value)
                seen.add(value)
    found = tuple(ids if preserve_order else sorted(ids))
    return found if limit is None else found[:limit]


def selection_evidence(requested, projects, geographic_scope):
    found = sorted({p['fongim_project_id'] for p in projects})
    missing = sorted(set(requested) - set(found))
    return {"source_type": "fongim_structured", "source_family": "FONGIM intervention data",
            "document_title": "FONGIM requested project-record lookup", "organization": "FONGIM",
            "document_type": "structured_operational_data", "section": "Exact requested identifiers",
            "geographic_scope": geographic_scope, "page": None,
            "content": f"Fresh FONGIM lookup in {geographic_scope}. Requested source project IDs: {list(requested)}. "
            f"Returned source project IDs: {found}. IDs not returned within this source/geography selection: {missing}. "
            "No unrelated illustrative projects are substituted. Non-return does not establish that a project does not exist. "
            "Prior answer text supplied lookup identifiers only; all dates, status, donor and actor claims require the fresh project records."}


def fongim_roster_ids(text, limit=20, preserve_order=False):
    """Accept a source-qualified roster's labelled Project 32: convention.

    This is history lookup context only. Research queries still require ID
    labels; dates, counts and arbitrary bare numbers are never identifiers.
    """
    labelled=re.sub(r'\b(Project|Projet)\s+(\d+)(?=\s*(?:\*\*)?\s*[:—–])',
                    r'\1 ID \2',text,flags=re.I)
    return fongim_project_ids(labelled, limit=limit,
                              preserve_order=preserve_order)
