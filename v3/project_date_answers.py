"""Verified date filtering over fresh source records, with direct row citations."""
from datetime import datetime, timezone
import re
from project_dates import parsed_date, reported_end_window
from project_references import fongim_project_ids
from source_wave import _fold


def answer(question, ledger, language=None, asof=None):
    q = _fold(question)
    # Only a reported-date roster/filter, never programme synthesis or an
    # assertion that a project actually completed/delivered/reached people.
    if re.search(r'\b(compare|compar\w*|why|pourquoi|needs?|besoins?|priorit\w*|fund\w*|financ\w*|budget\w*|donors?|bailleurs?|reach|delivery|results?|impact|lessons?|successors?|successeur\w*)\b', q):
        return None
    asof = asof or datetime.now(timezone.utc).date()
    window = reported_end_window(question, asof)
    if window:
        if re.search(r'\b(risks?|risques?|continuity|continuit\w*|handover|sequenc\w*|who|qui|implement\w*|agencies|agences|actors?|acteurs?|sectors?|secteurs?)\b', q):
            return None
        from geographic_model import geographic_model
        if geographic_model().retrieval_place_names(question):
            return None
    year_match = re.findall(r'\b(?:reported (?:end|closing) dates?|end dates?|closing dates?|date de fin(?: declaree)?) (?:in|en) ((?:19|20)\d{2})\b', q)
    if window is None and len(set(year_match)) != 1:
        return None
    year = int(year_match[0]) if window is None else None
    period_text=re.sub(r'\bXI-IATI-EC_(?:INTPA|ECHO)-[^\s*;,\]\)]+', '', question)
    period_text=re.sub(r'\b\d{4}-PC-\d+\b','',period_text)
    if window is None and {int(y) for y in re.findall(r'\b(?:19|20)\d{2}\b',period_text)} != {year}:
        return None
    sources=[source for source,pattern in [('FONGIM',r'\bfongim\b'),('World Bank',r'\b(world bank|banque mondiale)\b'),('EU IATI',r'\b(eu|ue|intpa|echo|xi iati ec)\b')] if re.search(pattern,q)]
    if len(sources)!=1:
        return None
    source=sources[0]
    rows = [e for e in ledger if e.get('project_record',{}).get('source_namespace') == source]
    if not rows or len(rows)>12:
        return None
    facts = {str(e['project_record']['source_id']):e for e in rows}
    # Do not collapse contradictory source records into a single date.
    if len(facts) != len(rows):
        return None
    requested = set(map(str,fongim_project_ids(question))) if source=='FONGIM' else set(re.findall(r'\bP\d{6}\b', question.upper())) if source=='World Bank' else set(x.rstrip('.:') for x in re.findall(r'\bXI-IATI-EC_(?:INTPA|ECHO)-[^\s*;,\]\)]+', question))
    if source=='EU IATI' and requested-set(facts):
        return None
    if requested:
        facts = {key:row for key,row in facts.items() if key in requested}
    rows = sorted(facts.values(),key=lambda e:(str(e['project_record'].get('end_date') or ''),str(e['project_record']['source_id'])))
    matched = [e for e in rows if parsed_date(e['project_record'].get('end_date')) and (window[0] <= parsed_date(e['project_record']['end_date']).isoformat() <= window[1] if window else parsed_date(e['project_record']['end_date']).year==year)]
    other = [e for e in rows if e not in matched]
    missing = requested-set(facts)
    french = language=='French' or bool(re.search(r'\b(quels|quelles|dossiers|declaree|projets)\b', q))
    asof = asof or datetime.now(timezone.utc).date()
    cites = lambda entries:' '.join('['+e['evidence_id']+']' for e in entries)
    label = 'dossiers demandés' if requested and not missing else 'dossiers retournés' if requested else 'exemples retournés'
    en_label = 'requested records' if requested and not missing else 'returned records' if requested else 'returned examples'
    denominator = len(requested) if requested and not missing else len(rows)
    period_fr = f'entre le {window[0]} et le {window[1]} (bornes incluses)' if window else f'en **{year}**'
    period_en = f'from {window[0]} through {window[1]} (inclusive)' if window else f'in **{year}**'
    opening = (f'**{len(matched)} sur {denominator} {label}** ont une date de fin/clôture déclarée {period_fr}.' if french else
               f'**{len(matched)} of {denominator} {en_label}** report an end/closing date {period_en}.')
    opening = ('Dans ' if french else 'In ')+source+', '+opening+' '+cites(matched or rows)
    lines=[opening, '', '| Identifiant source | Projet | Date déclarée | Statut déclaré | Source |' if french else '| Source identifier | Project | Reported end/closing | Reported status | Evidence |', '|---|---|---|---|---|']
    def cell(value):
        return str(value if value not in (None,'') else ('non renseigné' if french else 'not reported')).replace('|','\\|').replace('\n',' ')
    for e in matched:
        p=e['project_record']
        title=str(p.get('title') or '')
        title=title[:160]+'…' if len(title)>160 else title
        identifier=('FONGIM project ID '+str(p['source_id'])) if source=='FONGIM' else str(p['source_id'])
        lines.append(f'| {cell(identifier)} | {cell(title)} | {cell(p.get("end_date"))} | {cell(p.get("status"))} | [{e["evidence_id"]}] |')
    if not matched:
        lines=lines[:1]
    if other:
        lines += ['', ('Autres dossiers retournés : ' if french else 'Other returned records: ')+ '; '.join(
            f'{cell(e["project_record"]["source_id"])} — {cell(e["project_record"].get("end_date"))} [{e["evidence_id"]}]' for e in other)+'.']
    if missing:
        selection=[e for e in ledger if e.get('section')=='Exact requested identifiers']
        lines += ['', ('Identifiants non retournés dans cette sélection : ' if french else 'Identifiers not returned in this selection: ')+', '.join(sorted(missing))+'. '+cites(selection)]
    conflicts = [e for e in matched if parsed_date(e['project_record']['end_date'])<asof and
                 _fold(e['project_record'].get('status')) in ('en cours','active','implementation','ongoing')]
    if conflicts:
        lines += ['', (f'{len(conflicts)} dossier(s) associent un statut actif à une date de fin passée au {asof} : conflit de registre non résolu.' if french else
                        f'{len(conflicts)} record(s) combine an active status with a past reported end date as of {asof}: unresolved registry conflicts.')+' '+cites(conflicts)]
    syncs=sorted({str(e['project_record'].get('source_updated_at'))[:10] for e in rows if e['project_record'].get('source_updated_at')})
    note=('Dates et statuts déclarés, sans preuve d’achèvement réel ou de livraison actuelle. ' if french else 'Reported dates and status do not establish actual completion or current delivery. ')
    if window:
        note += (f'Fenêtre calculée au {asof}, distincte de la date de publication ou de synchronisation. ' if french else f'Window resolved as of {asof}, independently of source publication or sync dates. ')
    if syncs:
        note+=('Mise à jour source : ' if french else 'Source update/sync: ')+', '.join(syncs)+'. '
    if not requested:
        note+=('Sélection bornée, pas un inventaire exhaustif.' if french else 'Bounded source examples, not a complete portfolio.')
    lines += ['',note+' '+cites(rows[:4])]
    return '\n'.join(lines), {'method':'verified_project_date_filter','year':year,'window_start':window[0] if window else None,'window_end':window[1] if window else None,'source_namespace':source,
        'requested_ids':sorted(requested),'returned_ids':sorted(facts),
        'matching_ids':[str(e['project_record']['source_id']) for e in matched],
        'missing_ids':sorted(missing),'query_date':str(asof)}
