"""Compact synthesis views; originals and citation IDs remain immutable.

Only document text and the two large FONGIM relationship tables are excerpted.
Numeric structured observations and their scope/period caveats stay intact.
No model generates these summaries; all excerpts are exact source substrings.
"""
from collections import defaultdict
import json
import re
import unicodedata


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
    return tuple(str(item.get(k) or '') for k in keys) + (' '.join(str(item.get('content') or '').split()),)


def results_table(content):
    """Recognize quantitative indicator tables without interpreting their figures."""
    text=fold(content)
    return (len(re.findall(r'\b\d[\d,.%]*',text))>=8
            and bool(re.search(r'\b(indicators?|indicateurs?)\b',text))
            and bool(re.search(r'\b(targets?|cibles?)\b',text))
            and bool(re.search(r'\b(results?|resultats?|achievements?|realisations?)\b',text))
            and bool(re.search(r'\b(sectors?|secteurs?|disaggregation|desagregation|progress|progres)\b',text)))


def response_coverage_workflow(question):
    """Coverage language can ask for reported response without saying 'results'."""
    text=fold(question)
    return bool(re.search(r'\b(coverage|covered|uncovered|couverture|couverts?|couvertes?)\b|response gaps|lacunes? de la reponse',text)
                and re.search(r'\b(needs?|besoins?|response|reponse|humanitarian|humanitaire|sectors?|secteurs?)\b',text))


def results_table_guard(ledger, depth):
    if depth=='quick':
        return ''
    ids=[item['evidence_id'] for item in ledger if item.get('source_type')=='knowledge_base_document'
         and results_table(item.get('content',''))]
    if not ids:
        return ''
    return ('RESULTS TABLE INTERPRETATION CHECK for '+', '.join(ids)+': '
        'Keep publisher/implementing-partner columns separate from cluster/sector columns. '
        'A dash or blank in Total results is unreported, even when Progress displays 0%; '
        'claim zero people only if Total results explicitly contains numeric zero. '
        'A rounded 0% can accompany a positive result and does not imply zero delivery. '
        'Annual-target progress is not coverage of needs. Some Total needs cells may contain values '
        'while others are missing: describe denominators row by row, do not claim all are absent. '
        'A needs-coverage ratio requires compatible population, geography, period and measure definitions; '
        'do not substitute an annual target or combine indicators into unique people. Cite the exact table.')


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
    # Relevance budgets can favor narrative introductions over the very tables
    # needed to compare reported achievements with targets. Keep every retrieved
    # results-table chunk for this narrow workflow, including repeated headers
    # and period footnotes; do not calculate or assume indicator comparability.
    quantitative_workflow=depth!='quick' and (response_coverage_workflow(question) or bool(re.search(
        r'\b(delivery|reach|reached|results?|achievements?|targets?|progress|resultats?|realisations?|atteints?|cibles?|progres)\b',fold(question))))
    table_ids={item['evidence_id'] for item in deduplicated
               if quantitative_workflow and item.get('source_type')=='knowledge_base_document'
               and results_table(item.get('content',''))}
    doc_ids.update(table_ids)
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
        if (item.get('source_type') == 'knowledge_base_document' and not exhaustive and item['evidence_id'] not in table_ids) or (section in ('Organization-sector relationships','Sector-organization relationships') and not exhaustive):
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
        'retained_results_table_ids':sorted(table_ids),
        'original_content_chars':sum(len(str(e.get('content') or '')) for e in ledger),
        'synthesis_content_chars':sum(len(str(e.get('content') or '')) for e in selected)}


def serialize(ledger):
    """Source headers once, evidence IDs/locators/scopes beside every observation."""
    shared_keys = ('source_family','source_type','document_title','organization','document_type',
        'version','publication_date','valid_from','valid_until','reference_period_start',
        'reference_period_end','source_endpoint','release_id')
    sources, blocks = {}, []
    for item in ledger:
        metadata = {k:item[k] for k in shared_keys if item.get(k) not in (None,'',[],{})}
        key = json.dumps(metadata,sort_keys=True,ensure_ascii=False,default=str)
        if key not in sources:
            sources[key] = f'S{len(sources)+1}'
            blocks.append('SOURCE HEADER '+sources[key]+': '+key)
        fields = {k:item[k] for k in ('page','section','locator','geographic_scope','geographic_precision',
            'admin1_name','admin2_name','admin_level','retrieved_at','record_id','chunk_id','evidence_types')
            if item.get(k) not in (None,'',[],{})}
        if item.get('normalized_sectors'):
            fields['sector_cues'] = list(item['normalized_sectors'])
        blocks.append(f"[{item['evidence_id']}] SOURCE {sources[key]} " +
            json.dumps(fields,ensure_ascii=False,separators=(',',':'),default=str) + '\n' + str(item.get('content') or ''))
    return 'Cite evidence IDs [E..], never source header IDs. Only supplied excerpts support claims.\n'+'\n\n'.join(blocks)


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
