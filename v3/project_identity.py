"""Keep source project identifiers beside displayed names without a model pass.

Only unambiguous names from the current retrieved FONGIM examples qualify.
Identifiers support later lookup scope; they never establish status or results.
"""
import re
from source_wave import _fold


def preserve_project_identifiers(answer, ledger, question=''):
    # Keep a project-specific answer identifiable even when the model omits
    # the ID from its heading. The question alone cannot establish identity:
    # require the same exact identifier in the fresh source evidence.
    missing = []
    for pid in dict.fromkeys(re.findall(r'\bP\d{5,}\b', question, re.I)):
        if re.search(r'\b' + re.escape(pid) + r'\b', answer, re.I):
            continue
        source = next((item['evidence_id'] for item in ledger
            if str(item.get('source_family', '')).startswith(('IEG', 'World Bank', 'IATI'))
            and re.search(r'\b' + re.escape(pid) + r'\b', str(item.get('content', '')), re.I)), None)
        if source:
            missing.append(f'{pid.upper()} [{source}]')
    if missing:
        answer = '**Project: ' + ', '.join(missing) + '**\n\n' + answer
    records = {}
    for item in ledger:
        if item.get('source_family') != 'FONGIM intervention data':
            continue
        for row in item.get('project_referents', []):
            pid = row.get('project_id')
            if type(pid) is int and pid > 0 and row.get('project_name'):
                records.setdefault(pid, {'name': row['project_name'], 'evidence_ids': set()})['evidence_ids'].add(item['evidence_id'])
    if not records:
        return answer

    def identify(label):
        # A model may shorten a long displayed title with an ellipsis. Match
        # only its explicit leading words, never a sector, donor or status.
        prefix = re.split(r'…|\.{3}', label)[0]
        key = _fold(prefix)
        if not key or re.search(r'\b(?:project\s+id|id)\s*\d', key):
            return None
        hits = [pid for pid, row in records.items()
                if _fold(row['name']) == key or (len(key) >= 8 and len(key.split()) >= 2
                                               and _fold(row['name']).startswith(key + ' '))]
        return hits[0] if len(hits) == 1 else None

    def annotation(label, line):
        pid = identify(label)
        if pid is None or re.search(r'\b(?:project\s+ID|ID)\s*[:#]?\s*\d', line, re.I):
            return label
        source = sorted(records[pid]['evidence_ids'])[0]
        # Add a local citation for the newly displayed identifier, even if
        # the draft places its project citations at the end of a paragraph.
        return label + f' (project ID {pid}) [{source}]'

    lines = answer.splitlines()
    project_column = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith('|'):
            cells = line.split('|')
            header = next((i for i, cell in enumerate(cells)
                           if _fold(cell) in {'project', 'projet', 'project name', 'nom du projet'}), None)
            if header is not None:
                project_column = header
            elif project_column is not None and len(cells) > project_column:
                label = cells[project_column].strip()
                clean = label.replace('**', '')
                replacement = annotation(clean, line)
                if replacement != clean:
                    cells[project_column] = ' ' + replacement + ' '
                    lines[index] = '|'.join(cells)
        else:
            project_column = None
            match = re.match(r'^(\s*[-*]\s+\*\*)(.+?)(\*\*)(.*)$', line)
            if match:
                changed = annotation(match[2], line)
                if changed != match[2]:
                    # Keep the title bold; leave identifiers outside it.
                    suffix = changed[len(match[2]):]
                    lines[index] = match[1] + match[2] + match[3] + suffix + match[4]
    return '\n'.join(lines)
