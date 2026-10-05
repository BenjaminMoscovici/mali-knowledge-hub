"""Small per-thread query context. Nothing in this module is factual evidence.

State is reconstructed from the caller's bounded, owner-scoped history. No
conversation, private answer or entity mention is cached across users. Only
resolved research questions are carried forward; factual answers retrieve again.
"""
import re
from language import answer_language
from source_wave import _fold

SOCIAL = r'^(?:(?:hello|hi|hey|bonjour|salut|bonsoir)(?: there)?|thanks(?: a lot| so much)?|thank you(?: very much)?|merci(?: beaucoup)?|great thanks|ok thanks)$'
PLACE_STOP = {'mali','same','what','which','there','here','are','the','and','how','full','parent','path','name','region','cercle','commune','locality','men','women'}


def referenced_fongim_ids(question):
    """Bounded exact lookup scope; neither these IDs nor history are evidence."""
    match=re.search(r'FONGIM referenced project IDs:\s*(\d{1,10}(?:,\d{1,10}){0,19})(?:\.|$)',question)
    return tuple(dict.fromkeys(int(x) for x in match.group(1).split(','))) if match else ()


def places(question):
    from geographic_model import geographic_model
    model=geographic_model()
    words=_fold(question).split()
    names={" ".join(words[i:i+n]) for i in range(len(words))
           for n in range(1,min(model.max_name_words,len(words)-i)+1)
           if " ".join(words[i:i+n]) in model.names and " ".join(words[i:i+n]) not in PLACE_STOP}
    names={n for n in names if len(n)>2 and not any(n!=other and (' '+n+' ') in (' '+other+' ') for other in names)}
    # The registered place "All" is not the quantifier in "all 999 of them".
    if re.search(r'\ball\s+(?:\d+|of|the|those|these|them)\b',_fold(question)):
        names.discard('all')
    return sorted(names) or (['Mali'] if re.search(r'\bmali\b',_fold(question)) else [])


def describe(question):
    q=_fold(question)
    topic='other';metrics=[]
    if re.search(r'\b(how many|combien)\b',q) and re.search(r'\b(communes?|municipalit\w*|cercles?|localit\w*)\b',q):
        topic='administrative_count'
        for p,m in [(r'communes?|municipalit\w*','communes'),(r'cercles','cercles'),(r'localit\w*','localities')]:
            if re.search(r'\b(?:'+p+r')\b',q):metrics.append(m)
    elif re.search(r'\b(parent|hierarch\w*|appartien\w*)\b',q):topic='hierarchy';metrics=['parent hierarchy']
    elif re.search(r'\b(dtm|idps?|pdi|displace\w*|deplace\w*)\b',q):topic='displacement';metrics=['returned IDPs' if re.search(r'returned|retourne',q) else 'IDPs']
    elif re.search(r'\b(population|habitants?|rgph\w*|demograph\w*)\b',q):topic='population';metrics=['population']
    elif re.search(r'\b(cadre harmonis\w*|ch|food security|securite alimentaire)\b',q):topic='food_security';metrics=['classification and phase population']
    elif re.search(r'\b(funding|fts|financ\w*|requirements?|targeted|cible\w*)\b',q):
        topic='funding'
        for pattern,metric in [(r'funding|fts|financ\w*','reported funding'),(r'requirements?|besoins financiers','requirements'),(r'targeted|cible\w*','people targeted')]:
            if re.search(pattern,q):metrics.append(metric)
    elif re.search(r'\b(needs?|besoins?|hapi)\b',q):topic='needs';metrics=['people in need']
    elif re.search(r'\b(sne\w*|strateg\w*|priorit\w*)\b',q):topic='strategy';metrics=['stated priorities']
    elif re.search(r'\b(ieg|evaluation|evaluations|learning|lessons)\b',q):topic='project_learning';metrics=['evaluation findings']
    elif re.search(r'\b(3w|organisations?|organizations?|actors?|acteurs?)\b',q):topic='operational_presence';metrics=['recorded actor presence']
    elif re.search(r'\b(projects?|projets?|eib|bei|fongim)\b',q):topic='projects';metrics=['recorded projects']
    level=next((level for level in ['commune','cercle','region','arrondissement'] if re.search(r'\b'+level+r'\b',q)),None)
    if topic=='administrative_count' and not level:level='region'
    sex='female' if re.search(r'\b(women|female|femmes?)\b',q) else ('male' if re.search(r'\b(men|male|hommes?)\b',q) else None)
    entities=re.findall(r'\bP\d{5,}\b',question,re.I)
    if re.search(r'\bkabala\b',q):entities.append('EIB Kabala drinking-water project')
    if re.search(r'\bsnedd\b',q):entities.append('SNEDD')
    sources=[]
    for pattern,label in [(r'\bhapi\b','OCHA HAPI'),(r'\bdtm\b','IOM DTM'),(r'\bfts\b','OCHA FTS'),(r'\bfongim\b','FONGIM'),(r'\bieg\b','IEG'),(r'world bank|banque mondiale','World Bank'),(r'\beib\b|\bbei\b','EIB'),(r'\bsnedd\b','SNEDD'),(r'\b3w\b','OCHA 3W'),(r'cadre harmonis','Cadre Harmonise')]:
        if re.search(pattern,q):sources.append(label)
    return {'context_only':True,'topic':topic,'metrics':metrics,'geography':places(question),
            'administrative_level':level,'time_period':re.findall(r'\b(?:19|20)\d{2}\b',question),
            'sex':sex,'entities':list(dict.fromkeys(entities)),'source_families':sources,
            'unresolved_question':None,'last_question':question[:1600],'language':answer_language(question)}


def state_from_history(messages):
    state={}
    for message in messages[-10:]:
        # Assistant text is never parsed for asserted numbers, dates or facts.
        # Its standalone_question is the question already resolved by this API.
        question=message.get('standalone_question')
        if not question and message.get('role')=='user':question=message.get('content')
        if isinstance(question,str) and question.strip() and not re.match(SOCIAL,_fold(question)):
            candidate=describe(question)
            # Substantive standalone topic changes replace all old slots.
            if candidate['topic']!='other' or not state:
                state=candidate
        # Identifiers in the previous displayed list delimit "which of those".
        # They are lookup keys, never evidence for status, dates or funding.
        if message.get('role')=='assistant' and state.get('topic')=='projects':
            text=str(message.get('content') or '')[:6000]
            ids=re.findall(r'\b(?:project\s+ID|ID)\s*[:#]?\s*(\d{1,10})\b',text,re.I)
            state['mentioned_project_ids']=list(dict.fromkeys(int(x) for x in ids))[:20]
    return state


def clarification(kind,language):
    if language=='French':
        return {'place':'De quel lieu parlez-vous (région, cercle ou commune) ?',
                'metric':'Quelle mesure souhaitez-vous : les besoins financiers, le financement déclaré ou les personnes ciblées ?',
                'entity':'De quel projet parlez-vous ?',
                'indicator':'Quel indicateur concernant les femmes souhaitez-vous : population, bénéficiaires ou personnel des organisations ?'}[kind]
    return {'place':'Which place do you mean (region, cercle or commune)?',
            'metric':'Which measure do you mean: financial requirements, reported funding or people targeted?',
            'entity':'Which project do you mean?',
            'indicator':'Which indicator about women do you mean: population, beneficiaries or organisation staff?'}[kind]


def replace_place(base,old,new,level=None):
    target=new+((' '+level) if level and level not in _fold(new).split() else '')
    if old:
        # Match normalized aliases back to exact surface spans, including accents.
        pattern=re.compile(r'\b[\wÀ-ÿ]+(?:[-’\']\w+)*\b')
        tokens=list(pattern.finditer(base))
        for name in sorted(old,key=len,reverse=True):
            n=len(_fold(name).split())
            for i in range(len(tokens)-n+1):
                a,b=tokens[i].start(),tokens[i+n-1].end()
                if _fold(base[a:b])==_fold(name):
                    following=re.match(r'\s+(region|cercle|commune)\b',base[b:],re.I)
                    if following:b+=following.end()
                    return base[:a]+target+base[b:]
    if re.search(r'\b(there|here)\b',base,re.I):
        return re.sub(r'\b(there|here)\b','in '+target,base,flags=re.I)
    return base.rstrip(' ?')+' in '+target+'?'


def resolve(question,messages):
    """Resolve high-confidence ellipses; delegate genuinely semantic ones only."""
    q=_fold(question);state=state_from_history(messages)
    language=answer_language(question)
    result={'standalone_question':question,'state':state,'method':'standalone',
            'clarification_required':False,'needs_model':False,'language':language}
    if re.match(SOCIAL,q):return result
    deictic=bool(re.search(r'\b(there|here|that area|this area|la bas|cette zone)\b',q))
    # "How many are there in Mali?" has an explicit place; existential
    # "there" must not turn an already scoped lookup into clarification.
    if deictic and places(question):deictic=False
    pronoun=bool(re.search(r'\b(it|its|them|those|that|ses|son|sa|lesquels|lesquelles)\b',q))
    current=describe(question)
    explicit_scope=bool(current['geography'] or current['source_families'] or current['entities'])
    # Pronouns and conjunctions inside a fully scoped question do not make it
    # an ellipse. In particular, "establish that" is not a context reference.
    if explicit_scope and not re.match(r'^(and|et|same|what about|qu en est)\b',q):
        pronoun=False
    sex=bool(re.search(r'\b(women|female|femmes?|men|male|hommes?)\b',q))
    followup=deictic or pronoun or bool(re.match(r'^(and|et|same|what about|qu en est|at .*level)\b',q)) or (sex and len(q.split())<=5)
    if state and len(q.split())<=4 and describe(question)['topic']=='other' and places(question):followup=True
    def ask(kind):
        result.update(method='clarification',clarification_required=True,
                      clarification_answer=clarification(kind,language))
        result['state']={**state,'context_only':True,'unresolved_question':question}
        return result
    if deictic and len(state.get('geography',[]))!=1:return ask('place')
    if not state:
        if pronoun and len(q.split())<=10:return ask('entity')
        result['state']=current
        return result
    if not followup:
        result['state']=describe(question)
        return result
    if pronoun and re.search(r'how much|combien|quelle mesure',q) and len(state.get('metrics',[]))>1:return ask('metric')
    if pronoun and len(state.get('entities',[]))>1:return ask('entity')
    if sex and state.get('topic') not in {'population','displacement','needs'}:return ask('indicator')
    base=state.get('last_question','')
    new=describe(question)
    rewritten=None
    if new['geography'] and len(new['geography'])==1 and len(q.split())<=10 and state.get('last_question'):
        # A number of administrative units at national level carries to the
        # named region. A explicitly named cercle/commune scope stays at that level.
        rewritten=replace_place(base,state['geography'],new['geography'][0],state.get('administrative_level'))
    elif sex:
        target='female' if re.search(r'women|female|femme',q) else 'male'
        if state['topic']=='population':
            rewritten=re.sub(r'\b(?:female |male |women |men |feminine |masculine )?population\b',target+' population',base,flags=re.I)
        else:rewritten=base.rstrip(' ?')+'; report the '+target+' sex-disaggregated observations if supplied, otherwise state the missing breakdown.'
    elif re.search(r'\b(at|au|a|cercle|commune|region)\b.*\blevel\b|niveau',q) and new['administrative_level']:
        old=state.get('administrative_level')
        rewritten=re.sub(r'\b'+old+r'\b',new['administrative_level'],base,flags=re.I) if old else base.rstrip(' ?')+' at '+new['administrative_level']+' level?'
    elif new['time_period'] and len(q.split())<=6:
        old=state.get('time_period',[])
        if len(old)==1 and len(new['time_period'])==1:rewritten=base.replace(old[0],new['time_period'][0])
    elif 'returned' in q and state.get('topic')=='displacement':
        rewritten=re.sub(r'\bIDPs?\b','returned IDPs',base,flags=re.I)
    elif deictic:
        rewritten=re.sub(r'\b(there|here|that area|this area)\b',state['geography'][0]+' '+(state.get('administrative_level') or 'region'),question,flags=re.I)
    elif pronoun and state.get('topic')=='administrative_count' and re.search(r'\b\d+\b',q):
        referents=', '.join(state['metrics'])
        rewritten=('Verify the numerical premise and funding claim, without assuming either is true: '+question+
                   ' Context: '+base+'. The referents are administrative '+referents+
                   ', not intervention projects. Verify their count against the geographic registry; do not change the referent to projects.')
    elif pronoun and (len(state.get('entities',[]))==1 or state.get('topic')=='projects'):
        rewritten=question+' Research subject: '+base
        if state.get('topic')=='projects' and re.search(r'\b(those|them|lesquels|lesquelles)\b',q):
            ids=state.get('mentioned_project_ids',[])
            if not ids:return ask('entity')
            rewritten+='; FONGIM referenced project IDs: '+','.join(map(str,ids))+'. Restrict the answer to these previously mentioned identifiers; recheck every status/date in the underlying evidence.'
    if rewritten and rewritten!=question:
        result.update(standalone_question=rewritten,method='structured_context',state=describe(rewritten))
        result['state']['language']=language
        return result
    # Complex topic transitions and references to a particular finding need
    # the existing semantic resolver, with a bounded context-only prompt.
    result.update(method='semantic_context',needs_model=True)
    return result
