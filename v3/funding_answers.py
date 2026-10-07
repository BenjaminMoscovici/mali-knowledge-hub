"""Cited arithmetic over compatible funding records, never inferred allocations."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from routing import _bounded_fts, _normal


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n=Decimal(str(value))
        return n if n.is_finite() and n>=0 else None
    except (InvalidOperation, ValueError):
        return None


def display(value):
    if value is None:
        return None
    return format(value, ',f').rstrip('0').rstrip('.') if '.' in format(value, ',f') else format(value, ',f')


def answer(question, ledger, language=None):
    q=_normal(question)
    if not _bounded_fts(question) or re.search(
        r'\b(?:disburs\w*|decaisse\w*|commit\w*|engage\w*|pledges?|'
        r'why|pourquoi|predict\w*|forecast\w*|prevoir|will|sufficient|suffisan\w*|'
        r'changes?|trends?|evolution|increas\w*|decreas\w*|hausse|baisse|differences?|'
        r'convert\w*|conversion|exchange)\b',q):
        return None
    rows=[e for e in ledger if e.get('funding_record',{}).get('source_namespace')=='FTS']
    if not rows or len(rows)>8:
        return None
    required_keys={'source_id','year','currency','name','plan_code','requirements','reported_funding','publisher_percent','funding_definition'}
    if any(not required_keys.issubset(e['funding_record']) or
           not e['funding_record'].get('source_id') or
           not isinstance(e['funding_record'].get('year'),int) or
           e['funding_record'].get('scope')!='Mali; national plan/year only' for e in rows):
        return None
    requested_years={int(y) for y in re.findall(r'\b(?:19|20)\d{2}\b',q)}
    if requested_years-set(e['funding_record']['year'] for e in rows):
        return None
    ids=[e['funding_record']['source_id'] for e in rows]
    if len(set(ids))!=len(rows) or any(not re.fullmatch(r'E\d+',str(e.get('evidence_id',''))) for e in rows):
        return None
    facts=[]
    for e in rows:
        p=e['funding_record']
        if not p.get('comparable_within_record') or p.get('amount_unit')!='currency_unit' or not re.fullmatch(r'[A-Z]{3}',p.get('currency','')):
            return None
        required,funded=number(p.get('requirements')),number(p.get('reported_funding'))
        # Invalid source values are not silently turned into missing or zero.
        if any(p.get(key) is not None and value is None for key,value in
               [('requirements',required),('reported_funding',funded),('publisher_percent',number(p.get('publisher_percent')))]):
            return None
        difference=required-funded if required is not None and funded is not None else None
        percent=(funded/required*100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP) if required and funded is not None else None
        facts.append((e,required,funded,difference,percent))
    french=language=='French' or bool(re.search(r'\b(?:quels|quelle|montants?|pourcentage|comparez|financement)\b',q))
    unknown='non renseigné' if french else 'not reported'
    cell=lambda value:str(value if value not in (None,'') else unknown).replace('|','\\|').replace('\n',' ')
    money=lambda value:display(value) if value is not None else unknown
    lines=[('Voici les montants FTS déclarés et les calculs par plan/année. Les financements hors plan restent séparés.' if french else
            'These are the reported FTS amounts and calculations for each plan/year. Funding outside a specified plan remains separate.'),'',
        '| Année / plan | Devise | Besoins financiers | Financement déclaré | Besoins − financement (calcul) | % calculé | % arrondi source | Source |' if french else
        '| Year / plan | Currency | Requirements | Reported funding | Requirements − funding (calculated) | Calculated % | Source-rounded % | Evidence |',
        '|---|---|---|---|---|---|---|---|']
    audits=[]
    for e,required,funded,difference,percent in sorted(facts,key=lambda v:(v[0]['funding_record']['year'],str(v[0]['funding_record'].get('plan_id') or 'zz'))):
        p=e['funding_record']
        label=f'{p["year"]} / {p.get("plan_code") or ("hors plan/non précisé" if french else "outside/unspecified plan")}'
        pub=number(p.get('publisher_percent'))
        pct=(display(percent)+'%') if percent is not None else unknown
        pubpct=(display(pub)+'%') if pub is not None else unknown
        lines.append(f'| {cell(label)} | {p["currency"]} | {money(required)} | {money(funded)} | {money(difference)} | {pct} | {pubpct} | [{e["evidence_id"]}] |')
        audits.append({'source_id':p['source_id'],'evidence_id':e['evidence_id'],'currency':p['currency'],
                       'requirements_minus_funding':display(difference),'calculated_percent':display(percent)})
    lines += ['', ('**Méthode :** besoins financiers moins financement déclaré ; pourcentage calculé = financement ÷ besoins × 100, arrondi à deux décimales. Le pourcentage arrondi par la source est conservé séparément. Sans besoins financiers déclarés, aucun écart ni pourcentage n’est calculé.' if french else
        '**Method:** requirements minus reported funding; calculated percentage = funding ÷ requirements × 100, rounded to two decimals. The publisher’s rounded percentage is retained separately. Missing requirements do not support a gap or percentage calculation.')]
    for e,*_ in facts:
        p=e['funding_record']
        lines += ['', f'{cell(p["year"])} / {cell(p.get("plan_code"))}: {cell(p["name"])}. '+
                  ('Mise à jour source : ' if french else 'Source update: ')+cell(p.get('source_updated_at'))+'; '+
                  ('récupéré le ' if french else 'retrieved ')+cell(p.get('retrieved_at'))+'. '+cell(p['funding_definition'])+f' [{e["evidence_id"]}]']
    lines += ['', ('Un écart positif est un déficit arithmétique de financement ; un écart négatif indique un financement supérieur aux besoins financiers déclarés. Ces montants nationaux ne démontrent ni décaissement, ni livraison, ni couverture de besoins locaux. Aucun total interplans ou interannées ni conversion de devises n’a été effectué.' if french else
        'A positive balance is an arithmetic financing gap; a negative balance means reported funding exceeds requirements. These national figures do not establish disbursement, delivery or local needs coverage. No cross-plan/year total or currency conversion is performed.')]
    return '\n'.join(lines),{'method':'verified_funding_arithmetic','records':audits}
