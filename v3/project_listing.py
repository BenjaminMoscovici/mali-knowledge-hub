"""Render simple FONGIM date rosters from freshly retrieved structured facts.

This narrow path never answers joined analysis, amounts, impact, or pronouns.
Incomplete or conflicting structured inputs retain ordinary synthesis.
"""
import ast
import json
import re
from datetime import timedelta
from project_dates import ending_intent, parsed_date
from source_wave import _fold


def render(ledger, question, language='English'):
    q = _fold(question)
    if 'fongim' not in q or not ending_intent(question):
        return None
    if re.search(r'\b(needs?|besoins?|priorities|priorites|national|eu|ue|align\w*|compare\w*|compar\w*|funding|financ\w*|delivery|results?|resultats?|coverage|couverture|why|how|comment|pourquoi|ceux|celles)\b|\b(of those|those projects|these projects|ces projets)\b',q):
        return None
    if not re.search(r'\b(which|list|give|quels?|quelles?|liste|donne)\b',q):
        return None
    if not (re.search(r'\b180\b',q) or re.search(r'\b(?:six|6)\s+(?:months|mois)\b',q)):
        return None
    screens = []
    for e in ledger:
        if e.get('source_type') == 'fongim_structured' and str(e.get('section') or '').startswith('Reported-date selection'):
            m=re.search(r'reported-date screening:\s*(\{.*?\})',str(e.get('content') or ''))
            if m:
                try: screens.append((e['evidence_id'],json.loads(m[1])))
                except ValueError: return None
    if len(screens)!=1:
        return None
    screen_id,screen=screens[0];start=parsed_date(screen.get('asof'));end=parsed_date(screen.get('window_end'))
    if not start or end != start+timedelta(days=180):
        return None
    explicit_dates=re.findall(r'\b\d{4}-\d{2}-\d{2}\b',question)
    if any(d not in (start.isoformat(),end.isoformat()) for d in explicit_dates):
        return None
    rows=[];seen={}
    for e in ledger:
        if e.get('source_type')!='fongim_structured' or e.get('section')!='Project-ID relationship':continue
        content=str(e.get('content') or '')
        pid=re.search(r'FONGIM project ID (\d+):\s*(.*?)\s*Recorded organization names:',content,re.S)
        sectors=re.search(r'Recorded sectors:\s*(\[[^\n]*?\])',content)
        status=re.search(r'Status:\s*([^;\n]+)',content)
        dates=re.search(r'start/end dates:\s*\S+\s*/\s*(\d{4}-\d{2}-\d{2})',content)
        if not all([pid,sectors,status,dates]):return None
        try: sector_values=ast.literal_eval(sectors[1])
        except (ValueError,SyntaxError):return None
        if not isinstance(sector_values,list) or not sector_values or not all(isinstance(v,str) for v in sector_values):return None
        reported_end=parsed_date(dates[1])
        if not reported_end:return None
        identity=(pid[2].strip().rstrip('.'),tuple(sector_values),status[1].strip(),reported_end)
        if pid[1] in seen and seen[pid[1]]!=identity:return None
        if pid[1] in seen:continue
        seen[pid[1]]=identity
        if _fold(status[1].strip()) in ('en cours','active','implementation','ongoing') and start<=reported_end<=end:
            sync=re.search(r'latest sync:\s*(\d{4}-\d{2}-\d{2}T[^\s;]+)',content)
            rows.append((pid[1],identity[0],sector_values,dates[1],status[1].strip(),e['evidence_id'],sync[1].rstrip('.') if sync else None))
    count=screen.get('upcoming_active_records')
    if type(count)!=int or count<0 or len(rows)>count or not rows:
        return None
    # Only display fields backed by the individually cited original records.
    def cell(value):return str(value).replace('|','\\|').replace('\n',' ').strip()
    french=language.lower().startswith(('fr','french'))
    intro=(f"Le filtre FONGIM indique **{count} dossiers avec un statut en cours et une date de fin déclarée entre {start} et {end}**. [{screen_id}]"
           if french else f"FONGIM screening reports **{count} records labelled ongoing with reported end dates between {start} and {end}**. [{screen_id}]")
    header=('| ID | Projet | Date de fin déclarée | Secteurs enregistrés | Statut enregistré |\n|---|---|---|---|---|'
            if french else '| ID | Project | Reported end date | Recorded sectors | Recorded status |\n|---|---|---|---|---|')
    table=[header]
    for pid,name,sectors,date,status,eid,_ in sorted(rows,key=lambda r:(r[3],int(r[0]))):
        table.append('| '+ ' | '.join(cell(v) for v in [pid,name,date,'; '.join(sectors),status])+f' [{eid}] |')
    caveat=("Ces exemples individuels fournis restent une liste bornée, pas une preuve indépendante d'un portefeuille exhaustif. Les dates et statuts déclarés ne prouvent ni l'achèvement effectif ni la livraison actuelle. Les libellés géographiques FONGIM restent ceux de cette source."
            if french else 'These supplied individual examples are a bounded list, not independent proof of a complete portfolio. Reported dates and status do not prove actual completion or current delivery. FONGIM geography retains its source labels.')
    syncs={}
    for r in rows:
        if r[6]:syncs.setdefault(r[6],r[5])
    if syncs:
        caveat += (' Synchronisation déclarée : ' if french else ' Reported synchronization: ')+ '; '.join(f'{stamp} [{eid}]' for stamp,eid in sorted(syncs.items()))+'.'
    return intro+'\n\n'+'\n'.join(table)+'\n\n'+caveat
