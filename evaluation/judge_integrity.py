"""Advisory quote-integrity checks; never rewrite analytical judgments.

An evaluator claim or finding is not an authoritative quotation merely because
it was returned by a model. Nonliteral quotations need review; this check does
not establish whether a paraphrased claim is correct or excuse a Hub failure.
"""
import re
import unicodedata
from pathlib import Path
import json
from .common import write_json


def normalized(text):
    text=unicodedata.normalize('NFKC',str(text or '')).replace('**','').replace('`','')
    return re.sub(r'\s+',' ',text).strip().casefold()


def inspect(directory):
    root=Path(directory);flags=[];checked=0
    for p in sorted((root/'judgments').glob('*.json')):
        j=json.loads(p.read_text());raw=json.loads((root/'raw'/p.name).read_text())
        if j['response_hash']!=raw['response_hash']:raise ValueError('Judge quote check response hash mismatch')
        answer=normalized((raw.get('response') or {}).get('answer',''))
        entries=[('claim',i,c['text']) for i,c in enumerate(j['result']['claims'])
                 if c['verdict'] in {'unsupported','contradicted','unassessable'}]
        entries += [('finding',i,f['answer_quote']) for i,f in enumerate(j['result']['findings'])]
        for kind,index,quote in entries:
            value=normalized(quote)
            if not value:continue
            checked+=1
            if value not in answer:
                flags.append({'attempt':p.stem,'response_hash':raw['response_hash'],
                              'kind':kind,'index':index,'returned_quote':quote,
                              'status':'NONLITERAL_QUOTE_REQUIRES_REVIEW'})
    report={'version':'judge-quote-integrity-1.0','checked_quotes':checked,'nonliteral_quotes':len(flags),
            'flags':flags,'score_override':False,
            'method':'NFKC, case-fold and whitespace/Markdown emphasis normalization; candidate answer must contain the returned quotation.',
            'limitations':['Nonliteral atomic claims may be paraphrases; this is an advisory review flag, not an automatic Hub failure or an analytical score correction.',
                           'A literal quotation does not prove entailment. Original model judgments and scores remain unchanged.']}
    write_json(root/'judge_integrity.json',report);return report
