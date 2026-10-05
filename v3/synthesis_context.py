"""Compact synthesis views; originals and citation IDs remain immutable.

Only document text and the two large FONGIM relationship tables are excerpted.
Numeric structured observations and their scope/period caveats stay intact.
No model generates these summaries; all excerpts are exact source substrings.
"""
from collections import defaultdict
import json
import re
import unicodedata
from structured_summary import compact_text, exact_sentences


def fold(value):
    value = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return ''.join(c for c in value if not unicodedata.combining(c))


def terms(question):
    text = fold(question)
    words = {w for w in re.findall(r'[a-z0-9]+', text) if len(w) > 3}
    words -= {'what', 'which', 'with', 'from', 'that', 'this', 'does', 'have', 'their',
              'documented', 'compare', 'distinguish', 'about', 'mali', 'evidence'}
    for pattern, extra in [
        (r'food|aliment|hunger|faim', {'food', 'alimentaire', 'agriculture', 'agricole'}),
        (r'displace|deplac|dtm', {'displacement', 'deplaces', 'deplacees', 'pdi'}),
        (r'health|sante', {'health', 'sante'}),
        (r'water|wash|eau|sanitation', {'wash', 'eau', 'assainissement'}),
        (r'ending|end dates|echeance', {'end', 'ending', 'echeance'}),
    ]:
        if re.search(pattern, text):
            words |= extra
    return words


def relevance(text, wanted):
    words = re.findall(r'[a-z0-9]+', fold(text))
    return sum(any(word.startswith(term) for word in words) for term in wanted)


def identity(item):
    # Identical words from different releases/pages/entities are independent evidence.
    keys = ('source_family', 'source_type', 'release_id', 'document_id', 'document_title',
            'chunk_id', 'record_id', 'page', 'locator', 'section', 'version',
            'geographic_scope', 'admin1_code', 'admin2_code', 'reference_period_start',
            'reference_period_end', 'population_category', 'population_status', 'unit')
    if item.get('source_type') == 'knowledge_base_document':
        # Ingestion chunk IDs do not make an otherwise identical passage on
        # the same document/page/version independent evidence.
        keys = tuple(k for k in keys if k not in ('chunk_id', 'record_id'))
    return tuple(str(item.get(k) or '') for k in keys) + (' '.join(str(item.get('content') or '').split()),)


def extract_spans(content, wanted, budget=2200, separator=None):
    """Select whole sentences/rows, with neighbors; never cut a number or qualifier."""
    if len(content) <= budget:
        return content, [(0, len(content))]
    if separator:
        ranges = []
        start = 0
        for match in re.finditer(separator, content):
            ranges.append((start, match.end()))
            start = match.end()
        ranges.append((start, len(content)))
    else:
        # Sentence boundaries only at whitespace following punctuation; keep decimals.
        ranges = []
        start = 0
        for match in re.finditer(r'(?<=[.!?])\s+(?=[A-ZÀ-Ö0-9])|\n\s*\n', content):
            ranges.append((start, match.end()))
            start = match.end()
        ranges.append((start, len(content)))
    if len(ranges) < 2:
        # A single indivisible table/paragraph stays whole rather than lose semantics.
        return content, [(0, len(content))]
    ranked = sorted(range(len(ranges)), key=lambda i: (-relevance(content[slice(*ranges[i])], wanted), i))
    chosen = {0}
    used = ranges[0][1] - ranges[0][0]
    # Always preserve explicit epistemic restrictions and conflicts.
    qualifiers = r'\b(?:not |never |only |missing|unknown|unverified|uncertain|conflict|cannot|no approved|ne pas|non |pas |limitation)'
    for i, (start, end) in enumerate(ranges):
        if re.search(qualifiers, fold(content[start:end])):
            chosen.add(i)
    used = sum(ranges[i][1] - ranges[i][0] for i in chosen)
    for i in ranked:
        if i in chosen:
            continue
        neighbors = {i} if separator else {j for j in (i-1, i, i+1) if 0 <= j < len(ranges)}
        added = neighbors - chosen
        size = sum(ranges[j][1] - ranges[j][0] for j in added)
        if used + size <= budget or len(chosen) == 1:
            chosen |= added
            used += size
    spans = []
    for i in sorted(chosen):
        start, end = ranges[i]
        if spans and spans[-1][1] == start:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
    return '\n[... exact excerpt; intervening text omitted ...]\n'.join(content[a:b] for a,b in spans), spans


def prepare(ledger, question, depth='balanced'):
    """Create an auditable prompt subset without changing/reassigning original IDs."""
    wanted = terms(question)
    exhaustive = bool(re.search(r'\b(all|every|complete|exhaustive|tous|toutes|complet\w*)\b',fold(question)))
    seen, deduplicated = set(), []
    duplicates = []
    for item in ledger:
        key = identity(item)
        if key in seen:
            duplicates.append(item['evidence_id'])
            continue
        seen.add(key)
        deduplicated.append(item)
    docs = defaultdict(list)
    for item in deduplicated:
        if item.get('source_type') == 'knowledge_base_document':
            docs[item.get('source_family')].append(item)
    doc_ids = set()
    limit = {'quick':3, 'balanced':4, 'deep':6}.get(depth,4)
    for family, items in docs.items():
        ranked = sorted(items, key=lambda e: (-relevance(e.get('content',''),wanted),
            -(e.get('similarity') or 0), e['evidence_id']))
        # Retain at least one chunk per retrieved document, including named targets.
        documents = set()
        for item in ranked:
            did = item.get('document_id') or item.get('document_title')
            if did not in documents:
                doc_ids.add(item['evidence_id']); documents.add(did)
        for item in ranked[:limit]:
            doc_ids.add(item['evidence_id'])
    selected, excerpts, omitted = [], {}, []
    for item in deduplicated:
        if item.get('source_type') == 'knowledge_base_document' and item['evidence_id'] not in doc_ids:
            omitted.append(item['evidence_id']); continue
        # These are two transposes of the same project-ID relationship, not extra facts.
        # Keep the sector orientation unless the question asks about actor breadth.
        breadth = bool(re.search(r'breadth|divers|multi.sector|organisation.*sector|organization.*sector',fold(question)))
        section = item.get('section')
        if section in ('Organization-sector relationships', 'Sector-organization relationships'):
            if section == ('Sector-organization relationships' if breadth else 'Organization-sector relationships'):
                omitted.append(item['evidence_id']); continue
        view = dict(item)
        content = str(item.get('content') or '')
        if (item.get('source_type') == 'knowledge_base_document' and not exhaustive) or (section in ('Organization-sector relationships','Sector-organization relationships') and not exhaustive):
            compact, spans = extract_spans(content, wanted,
                budget=3600 if depth=='deep' else 2200,
                separator=r';\s*' if item.get('source_type')=='fongim_structured' else None)
            view['content'] = compact
            if compact != content:
                view['content'] += '\nSelected exact spans only; omitted text cannot support claims. This is not a complete roster/table.'
                view['synthesis_spans'] = spans
                excerpts[item['evidence_id']] = spans
        selected.append(view)
    return selected, {'retrieved_items':len(ledger), 'synthesis_items':len(selected),
        'duplicate_ids':duplicates, 'omitted_ids':omitted, 'excerpt_spans':excerpts,
        'original_content_chars':sum(len(str(e.get('content') or '')) for e in ledger),
        'synthesis_content_chars':sum(len(str(e.get('content') or '')) for e in selected)}


def serialize(ledger, audit=None, question=''):
    """Source headers once, evidence IDs/locators/scopes beside every observation."""
    shared_keys = ('source_family','source_type','organization','document_type',
        'version','publication_date','valid_from','valid_until','reference_period_start',
        'reference_period_end','release_id','retrieved_at','geographic_scope','geographic_precision')
    sources, blocks = {}, []
    packed_ids = []
    include_urls = bool(re.search(r'\b(url|links?|liens?|consulter)\b|original source', fold(question)))
    prepared = []
    for item in ledger:
        metadata = {k:item[k] for k in shared_keys if item.get(k) not in (None,'',[],{})}
        if item.get('source_type') == 'knowledge_base_document' and item.get('document_title'):
            metadata['document_title'] = item['document_title']
        key = json.dumps(metadata,sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str)
        fields = {k:item[k] for k in ('page','section','locator',
            'admin1_name','admin2_name','admin_level','evidence_types')
            if item.get(k) not in (None,'',[],{})}
        if fields.get('section') == fields.get('locator'):
            fields.pop('section', None)
        content = str(item.get('content') or '')
        if item.get('source_type') != 'knowledge_base_document':
            content, packed = compact_text(content)
            if packed:
                packed_ids.append(item['evidence_id'])
            title = item.get('document_title')
            if title and title not in content:
                fields['document_title'] = title
        if include_urls:
            for field in ('source_url', 'source_endpoint'):
                if item.get(field):
                    fields[field] = item[field]
        if item.get('normalized_sectors'):
            fields['sector_cues'] = list(item['normalized_sectors'])
        units = list(exact_sentences(content)) if item.get('source_type') != 'knowledge_base_document' else [content]
        prepared.append((item, key, fields, units))
    memberships = defaultdict(set)
    for item, key, _, units in prepared:
        if item.get('source_type') == 'knowledge_base_document':
            continue
        for unit in units:
            if len(unit.strip()) >= 80:
                memberships[(key, unit.strip())].add(item['evidence_id'])
    shared = {key: ids for key, ids in memberships.items() if len(ids) >= 3}
    emitted = set()
    for item, key, fields, units in prepared:
        if key not in sources:
            sources[key] = f'S{len(sources)+1}'
            blocks.append('SOURCE HEADER '+sources[key]+': '+key)
        remaining = []
        references = []
        for unit in units:
            token = (key, unit.strip())
            if token not in shared:
                remaining.append(unit)
                continue
            references.append(token)
            if token not in emitted:
                emitted.add(token)
                ids = ', '.join('['+eid+']' for eid in sorted(shared[token]))
                blocks.append('SHARED EXACT PASSAGE — applies only to '+ids+':\n'+unit.strip())
        content = ''.join(remaining)
        if references:
            content += '\nIncludes the shared exact passages explicitly attributed to this evidence ID above.'
        blocks.append(f"[{item['evidence_id']}] SOURCE {sources[key]} " +
            json.dumps(fields,ensure_ascii=False,separators=(',',':'),default=str) + '\n' + content)
    text = ('Cite evidence IDs [E..], never source header IDs. Only supplied excerpts support claims. '
        'Original URLs and record/chunk anchors are available through each evidence ID in the source panel. '
        'Lossless JSON packing: __mkh_table represents rows with shared_fields recursively merged into '
        'each row; __mkh_missing_fields lists fields originally null, never zero. All original '
        'observations, values, scope, periods and restrictions remain applicable.\n'+'\n\n'.join(blocks))
    if audit is not None:
        audit.update(structured_summary_ids=packed_ids, serialized_chars=len(text),
                     shared_exact_passages=len(emitted), serialization_version='lossless-synthesis-1.0')
    return text


def availability_note(ledger, question):
    """Point to supplied examples without mistaking a bounded set for a full roster."""
    if not re.search(r'ending|end dates|echeance|termin', fold(question)):
        return ''
    ids = [e['evidence_id'] for e in ledger
           if e.get('source_type') == 'fongim_structured'
           and e.get('section') == 'Project-ID relationship'
           and 'start/end dates:' in str(e.get('content') or '')]
    if not ids:
        return ''
    return ('SUPPLIED PROJECT EXAMPLE INDEX (navigation only, not independent evidence): '
            + ', '.join('['+eid+']' for eid in ids)
            + '. These items contain individual project names, sectors and reported end dates. '
            'Answer the request to identify ending interventions with the relevant named examples '
            'and their reported dates, citing those items. The examples are a partial list; '
            'the aggregate screening count does not mean individual examples are unavailable. '
            'Do not infer names or dates for additional records not supplied.')
