"""Slot carry-over preserves query constraints and always performs fresh research."""
import sys
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient
from followup_context import resolve_slots
import web_api


def history(question):
    return [{'role': 'user', 'content': question},
            {'role': 'assistant', 'content': '999 people, all female, in 2099. [E99]'}]


@pytest.mark.parametrize('base,followup,required', [
    ('What is the 2023 population projection for Bandiagara region?', 'What about women?',
     ['female population', '2023', 'Bandiagara region']),
    ('Quelle est la population projetée de la région de Gao en 2023 ?', 'Et les hommes ?',
     ['male population', '2023', 'région de Gao']),
    ('What IDP stocks does DTM report for Socoura in September 2025?', 'What about women?',
     ['female sex-disaggregated', 'DTM', 'Socoura', 'September 2025', 'missing breakdown']),
    ('What intersectoral people-in-need observations are available for Mopti in OCHA HAPI?',
     'What about women?', ['female sex-disaggregated', 'intersectoral', 'Mopti', 'OCHA HAPI']),
    ('What is the 2023 population projection for Bandiagara region?', 'And in 2024?',
     ['2024', 'population projection', 'Bandiagara region']),
    ('Quelle est la population projetée de la région de Mopti en 2023 ?', 'Et en 2024 ?',
     ['2024', 'population projetée', 'région de Mopti']),
    ('What is the 2023 female population projection for Bandiagara region?', 'And at cercle level?',
     ['2023', 'female population', 'Bandiagara cercle']),
])
def test_preserved_slots_no_assistant_facts(base, followup, required):
    result = resolve_slots(followup, history(base))
    assert result and result['state']['context_only']
    assert all(word in result['standalone_question'] for word in required)
    assert '999' not in result['standalone_question'] and '2099' not in result['standalone_question']


def test_chains_sex_switch_social_and_topic_reset():
    prior = history('What is the 2023 population projection for Bandiagara region?')
    female = resolve_slots('What about women?', prior)['standalone_question']
    prior.extend([{'role':'user','content':'What about women?'},
                  {'role':'assistant','standalone_question':female,'content':'Wrong 999.'},
                  {'role':'user','content':'Thanks!'}])
    male = resolve_slots('What about men?', prior)['standalone_question']
    assert 'male population' in male and 'female population' not in male
    assert 'Bandiagara cercle' in resolve_slots('And at cercle level?', prior)['standalone_question']
    prior.append({'role':'user','content':'Which organisations operate in Gao?'})
    assert resolve_slots('What about women?', prior) is None


@pytest.mark.parametrize('base,followup', [
    ('Which organisations operate in Mopti?', 'What about women?'),
    ('Compare population and funding in Gao.', 'What about women?'),
    ('What female and male population projections exist for Gao?', 'What about women?'),
    ('What is the population of women in Gao?', 'What about men?'),
    ('What are the needs and population of Gao?', 'What about women?'),
    ('How many inhabitants are in Gao?', 'What about women?'),
    ('What IDP stock does DTM Round 83 September 2025 report for Socoura?', 'And in 2024?'),
    ('Compare the 2023 and 2024 population of Gao.', 'And in 2025?'),
    ('What population was reported on 2023-09-01 for Gao?', 'And in 2024?'),
    ('What is the population of Bamba commune in 2023?', 'And at commune level?'),
    ('What is the population of Unknownville region in 2023?', 'And at cercle level?'),
    ('What is the population of Gao in 2023?', 'What about women and children?'),
    ('What is the population of Gao in 2023?', 'Which of those are still active?'),
    ('What is the population of Gao in 2023?', 'Are all 999 of them EU-funded?'),
])
def test_ambiguity_and_unsupported_scope_keep_existing_resolver(base, followup):
    assert resolve_slots(followup, history(base)) is None


def test_api_skips_only_rewrite_and_retrieves_for_each_guest():
    requests = []
    def research(question, **kwargs):
        requests.append((question, kwargs))
        return {'answer':'Fresh evidence only [E01]', 'evidence':[{'evidence_id':'E01',
                'content':'Original sex-specific observation; not historical answer text.'}]}
    def no_rewrite(*args, **kwargs):
        raise AssertionError('unnecessary rewrite pass')
    engine = SimpleNamespace(generate_grounded_answer=research, is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=lambda *args:True, resolve_conversational_question=no_rewrite,
        source_inventory_answer=lambda:'', openai_client=None)
    client = TestClient(web_api.app, base_url='http://127.0.0.1:8765')
    with patch.dict(sys.modules, {'analysis_core':engine}):
        for place in ['Bandiagara', 'Gao']:
            response = client.post('/api/chat', json={'question':'What about women?',
                'prior_messages':history(f'What is the 2023 population projection for {place} region?')},
                headers={'Origin':'http://127.0.0.1:8765'})
            assert response.status_code == 200
            body = response.json()
            assert body['metrics']['context_resolution_method'] == 'structured_query_slots'
            assert body['metrics']['context_api_usage'] == {}
            assert body['evidence'][0]['evidence_id'] == 'E01'
            assert place in body['standalone_question'] and '999' not in body['standalone_question']
        assert len(requests) == 2 and requests[0][0] != requests[1][0]
        # Missing history must not inherit another guest's topic.
        response = client.post('/api/chat', json={'question':'What about women?'},
                               headers={'Origin':'http://127.0.0.1:8765'})
        assert response.status_code == 503
    client.close()


@pytest.mark.parametrize('roster,followup,required', [
    ('FONGIM records: Project ID 664; Project ID 434; Project ID 696; Project ID 32.',
     'Which of those projects have a reported end date in 2026?', ['FONGIM','32, 434, 664, 696','2026']),
    ('FONGIM records: Project ID 664; Project ID 32.',
     'Lesquels de ces projets ont une date de fin en 2026 ?', ['FONGIM','32, 664','2026']),
    ('World Bank records: P144442 and P176347.',
     'Which of those projects end in 2027?', ['World Bank','P144442, P176347','2027']),
    ('EU records: XI-IATI-EC_INTPA-2023-PC-34274 and XI-IATI-EC_ECHO-ECHO/-AF/BUD/2025/91017.',
     'Which of them have a reported end date in 2026?', ['XI-IATI-EC_INTPA-2023-PC-34274','XI-IATI-EC_ECHO-ECHO/-AF/BUD/2025/91017','2026']),
])
def test_project_date_filter_carries_only_identity_and_requested_calendar_period(roster,followup,required):
    result=resolve_slots(followup,[{'role':'assistant','content':roster+' All allegedly ended in 2099 and delivered to 999 people.'}])
    assert result and result['state']['context_only']
    assert all(value in result['standalone_question'] for value in required)
    assert '2099' not in result['standalone_question'] and '999' not in result['standalone_question']


@pytest.mark.parametrize('roster,followup', [
    ('FONGIM project ID 664 and World Bank P144442.', 'Which of those projects end in 2026?'),
    ('Projects A and B.', 'Which of those projects end in 2026?'),
    ('FONGIM project ID 664.', 'Which of those projects are EU-funded?'),
    ('FONGIM project ID 664.', 'Compare those projects with Mopti needs.'),
    ('FONGIM project ID 664. '+'x'*5900, 'Which of those projects end in 2026?'),
])
def test_ambiguous_project_sets_and_new_operations_keep_semantic_resolver(roster,followup):
    assert resolve_slots(followup,[{'role':'assistant','content':roster}]) is None


@pytest.mark.parametrize('question', ['Which of those projects have a reported end date in 2026?',
    'Which of those projects close in the next 6 months?'])
def test_project_filter_api_skips_rewrite_but_freshly_researches_source_ids(question):
    from project_references import fongim_project_ids
    calls=[]
    def research(question,**kwargs):
        assert fongim_project_ids(question)==(32,664,696)
        assert '2099' not in question
        calls.append(question)
        return {'answer':'Fresh source dates, not answer history. [E01]', 'evidence':[{'evidence_id':'E01','content':'Fresh lookup'}]}
    def forbidden(*a,**kw):
        raise AssertionError('project-set rewrite must be skipped')
    engine=SimpleNamespace(generate_grounded_answer=research,is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=lambda *args:True,resolve_conversational_question=forbidden,
        source_inventory_answer=lambda:'',openai_client=None)
    client=TestClient(web_api.app,base_url='http://127.0.0.1:8765')
    with patch.dict(sys.modules,{'analysis_core':engine}):
        response=client.post('/api/chat',json={'question':question,
            'prior_messages':[{'role':'assistant','content':'FONGIM records: Project ID 32; Project ID 664; Project ID 696. All ended in 2099.'}]},
            headers={'Origin':'http://127.0.0.1:8765'})
        assert response.status_code==200
        body=response.json()
        assert body['metrics']['context_resolution_method']=='structured_query_slots'
        assert body['metrics']['context_api_usage']=={}
        assert len(calls)==1 and body['evidence'][0]['content']=='Fresh lookup'
    client.close()


@pytest.mark.parametrize('roster,question', [
    ('FONGIM project ID 32; Project ID 664.', 'Which of those projects close in the next 6 months?'),
    ('World Bank P144442 and P176347.', 'Which of them have reported closing dates in the next 3 weeks?'),
    ('EU XI-IATI-EC_INTPA-2023-PC-34274.', 'Lesquels de ces projets ont une date de clôture dans les 3 prochains mois ?'),
])
def test_rolling_project_followups_freeze_query_window_not_historical_dates(roster,question):
    from project_dates import reported_end_window
    result=resolve_slots(question,[{'role':'assistant','content':roster+' End date 2099-12-31; 999 people reached.'}])
    assert result and result['state']['context_only']
    assert result['state']['time_period']==list(reported_end_window(question))
    assert reported_end_window(result['standalone_question'])==reported_end_window(question)
    assert '2099' not in result['standalone_question'] and '999' not in result['standalone_question']


@pytest.mark.parametrize('roster,question,source,ids', [
    ('FONGIM project ID 32; Project ID 664.',
     'Which of those projects have a reported end date between 2026-11-01 and 2026-12-31?',
     'FONGIM', [32, 664]),
    ('World Bank P144442 and P176347.',
     'Which of them have reported closing dates from 2027-01-01 to 2027-06-30?',
     'World Bank', ['P144442', 'P176347']),
    ('EU XI-IATI-EC_INTPA-2023-PC-34274.',
     'Lesquels de ces projets ont une date de clôture entre 2026-11-01 et 2027-01-31 ?',
     'EU IATI', ['XI-IATI-EC_INTPA-2023-PC-34274']),
    ('FONGIM project ID 664.',
     'Lesquels de ces projets ont une date de fin du 2026-11-01 au 2026-12-31 ?',
     'FONGIM', [664]),
])
def test_explicit_range_followups_keep_ids_and_fresh_date_window(
        roster, question, source, ids):
    from project_dates import reported_end_window
    result = resolve_slots(question, [{'role':'assistant', 'content':
        roster + ' End date 2099-12-31; reported reach 999.'}])
    assert result['state']['source'] == source
    assert result['state']['lookup_ids'] == ids
    assert result['state']['time_period'] == list(reported_end_window(question))
    assert reported_end_window(result['standalone_question']) == reported_end_window(question)
    assert '2099' not in result['standalone_question']
    assert '999' not in result['standalone_question']


@pytest.mark.parametrize('question', [
    'Which of those projects have a reported end date between 2027-01-01 and 2026-01-01?',
    'Which of those projects close from 2026-02-30 to 2027-01-01?',
    'Lesquels de ces projets ont une date de fin entre 2026-11-01 et 2026-12-31 et couvrent les besoins ?',
])
def test_invalid_or_analytical_explicit_range_followups_defer(question):
    assert resolve_slots(question, [{'role':'assistant', 'content':
        'FONGIM project ID 664.'}]) is None


@pytest.mark.parametrize('question', [
    'Which of those projects close in the next 0 months?',
    'Which of those projects close in the next 99 months?',
    'Which of those projects close in the next 3 months and have successor funding?',
    'Lesquels de ces projets ont une date de clôture dans les 3 prochains mois et couvrent les besoins ?',
])
def test_invalid_or_analytical_rolling_followups_defer(question):
    assert resolve_slots(question,[{'role':'assistant','content':'World Bank P144442.'}]) is None


@pytest.mark.parametrize('namespace,keep,exclude,question', [
    ('World Bank','P513735','P164032','Which of those projects close in the next 12 months?'),
    ('EU IATI','XI-IATI-EC_INTPA-2023-PC-34257','XI-IATI-EC_ECHO-ECHO/-AF/BUD/2026/91003',
     'Lesquels de ces projets ont une date de clôture dans les 3 prochains mois ?'),
])
def test_narrowed_date_table_does_not_reintroduce_excluded_records(namespace,keep,exclude,question):
    from project_date_answers import answer
    from datetime import date
    rows=[{'evidence_id':eid,'project_record':{'source_namespace':namespace,'source_id':pid,'end_date':end}}
          for eid,pid,end in [('E01',keep,'2026-12-07'),('E02',exclude,'2027-02-28')]]
    previous=f'For {namespace} project IDs {keep}, {exclude}, which have reported end dates between 2026-10-08 and 2027-01-08?'
    text,_=answer(previous,rows,asof=date(2026,10,8))
    assert exclude in text
    result=resolve_slots(question,[{'role':'assistant','content':text}])
    assert result['state']['lookup_ids']==[keep]
    assert exclude not in result['standalone_question']
    assert '2026-12-07' not in result['standalone_question']


def test_two_date_tables_are_ambiguous_context():
    table='| Source identifier | Project | Reported end/closing |\n|---|---|---|\n| P513735 | A | 2027-05-01 |\n'
    assert resolve_slots('Which of those projects close in the next 12 months?',
                         [{'role':'assistant','content':table+'\n'+table}]) is None


@pytest.mark.parametrize('language,followup', [
    ('English', 'Which of those projects have a reported end date in 2027?'),
    ('French', 'Lesquels de ces projets ont une date de fin en 2027 ?'),
])
@pytest.mark.parametrize('namespace,keep,mentioned', [
    ('FONGIM', '664', '32'),
    ('World Bank', 'P513735', 'P164032'),
    ('EU IATI', 'XI-IATI-EC_INTPA-2023-PC-34257',
     'XI-IATI-EC_INTPA-2023-PC-34274'),
])
def test_date_followup_uses_identifier_column_not_references_in_project_title(
        language, followup, namespace, keep, mentioned):
    from project_date_answers import answer
    from datetime import date
    label = lambda pid: 'FONGIM project ID '+pid if namespace == 'FONGIM' else pid
    rows = [{'evidence_id':'E01', 'project_record':{
        'source_namespace':namespace, 'source_id':keep, 'end_date':'2026-11-30',
        'title':'Successor to '+label(mentioned)}}]
    text, audit = answer(
        f'For {namespace} project IDs {keep}, which records have a reported end date in 2026?',
        rows, language, asof=date(2026,10,9))
    assert audit['matching_ids'] == [keep] and mentioned in text
    result = resolve_slots(followup, [{'role':'assistant','content':text}])
    expected = [int(keep)] if namespace == 'FONGIM' else [keep]
    assert result['state']['lookup_ids'] == expected
    assert result['state']['context_only']
    assert label(mentioned) not in result['standalone_question']
    assert '2026-11-30' not in result['standalone_question']


def test_fongim_date_table_excludes_ids_in_notes_and_rejects_ambiguous_tables():
    table = ('| Source identifier | Project | Reported end/closing |\n'
             '|---|---|---|\n'
             '| FONGIM project ID 664 | Selected | 2026-11-30 |\n')
    question = 'Which of those projects have a reported end date in 2027?'
    note = '\nOther returned records: FONGIM project ID 32 — 2027-01-01.\n'
    result = resolve_slots(question, [{'role':'assistant','content':table+note}])
    assert result['state']['lookup_ids'] == [664]
    assert resolve_slots(question, [{'role':'assistant','content':table+'\n'+table}]) is None


def test_fongim_title_reference_never_expands_fresh_api_lookup():
    from project_date_answers import answer
    from project_references import fongim_project_ids
    rows = [{'evidence_id':'E01', 'project_record':{
        'source_namespace':'FONGIM', 'source_id':'664', 'end_date':'2026-11-30',
        'title':'Successor to FONGIM project ID 32'}}]
    text, _ = answer('For FONGIM project ID 664, which records have a reported end date in 2026?', rows)
    calls = []
    def research(question, **kwargs):
        calls.append(question)
        assert fongim_project_ids(question) == (664,)
        return {'answer':'Fresh lookup [E01]', 'evidence':[
            {'evidence_id':'E01','content':'Fresh source record, not the previous answer.'}]}
    def forbidden(*args, **kwargs):
        raise AssertionError('No semantic rewrite needed for the selected ID column')
    engine = SimpleNamespace(generate_grounded_answer=research,
        is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=lambda *args:True,
        resolve_conversational_question=forbidden,
        source_inventory_answer=lambda:'', openai_client=None)
    with TestClient(web_api.app, base_url='http://127.0.0.1:8765') as client:
        with patch.dict(sys.modules, {'analysis_core':engine}):
            response = client.post('/api/chat', json={
                'question':'Which of those projects have a reported end date in 2027?',
                'prior_messages':[{'role':'assistant','content':text}]},
                headers={'Origin':'http://127.0.0.1:8765'})
    assert response.status_code == 200 and len(calls) == 1
    body = response.json()
    assert body['metrics']['context_resolution_method'] == 'structured_query_slots'
    assert body['metrics']['context_api_usage'] == {}
    assert body['evidence'][0]['content'] == 'Fresh source record, not the previous answer.'


@pytest.mark.parametrize('source,pid', [
    ('FONGIM','664'), ('World Bank','P513735'),
    ('EU IATI','XI-IATI-EC_INTPA-2023-PC-34274'),
])
@pytest.mark.parametrize('french', [False, True])
def test_active_date_subset_rechecks_changed_source_status(source, pid, french):
    from project_date_answers import answer
    row = {'evidence_id':'E01','project_record':{'source_namespace':source,
        'source_id':pid,'status':'En cours','end_date':'2026-11-30','title':'Selected'}}
    initial = f'For {source} project IDs {pid}, which active records have a reported end date in 2026?'
    text, _ = answer(initial, [row], language='French' if french else 'English')
    followup = ('Lesquels de ces projets ont une date de fin en 2026 ?' if french else
                'Which of those projects have a reported end date in 2026?')
    resolved = resolve_slots(followup, [{'role':'assistant','content':text}])
    assert resolved['state']['active_only'] is True
    assert list(map(str,resolved['state']['lookup_ids'])) == [pid]
    assert '2026-11-30' not in resolved['standalone_question']
    assert 'En cours' not in resolved['standalone_question']
    # A changed or unavailable status cannot inherit the earlier active label.
    for status in ['Closed', None]:
        fresh = dict(row, project_record=dict(row['project_record'], status=status))
        new_text, audit = answer(resolved['standalone_question'], [fresh],
                                  language='French' if french else 'English')
        assert audit['active_only'] and audit['matching_ids'] == []
        assert ('**0 sur 1' if french else '**0 of 1') in new_text


def test_active_date_subset_preserves_constraint_for_explicit_range():
    from project_date_answers import answer
    row = {'evidence_id':'E01','project_record':{'source_namespace':'FONGIM',
        'source_id':'664','status':'En cours','end_date':'2026-11-30','title':'Selected'}}
    text, _ = answer(
        'For FONGIM project ID 664, which active records have a reported end date in 2026?',
        [row])
    followup = ('Which of those projects have a reported end date '
                'between 2026-11-01 and 2026-12-31?')
    resolved = resolve_slots(followup, [{'role':'assistant','content':text}])
    assert resolved['state']['active_only'] is True
    assert resolved['state']['lookup_ids'] == [664]
    assert resolved['state']['time_period'] == ['2026-11-01', '2026-12-31']
    assert 'active records' in resolved['standalone_question']


def test_active_status_or_title_in_unfiltered_table_does_not_add_a_constraint():
    from project_date_answers import answer
    row = {'evidence_id':'E01','project_record':{'source_namespace':'FONGIM',
        'source_id':'664','status':'En cours','end_date':'2026-11-30',
        'title':'Filter uses reported active labels; missing or other statuses are not classified as active.'}}
    text, _ = answer('For FONGIM project ID 664, which records have a reported end date in 2026?', [row])
    resolved = resolve_slots('Which of those projects have a reported end date in 2026?',
                             [{'role':'assistant','content':text}])
    assert resolved['state']['active_only'] is False
    assert 'active records' not in resolved['standalone_question']
    row['project_record']['status'] = 'Closed'
    _, audit = answer(resolved['standalone_question'], [row])
    assert audit['matching_ids'] == ['664'] and not audit['active_only']


def test_active_date_filter_api_preserves_constraint_and_uses_fresh_status():
    from project_date_answers import answer
    row = {'evidence_id':'E01','content':'Fresh source record', 'project_record':{
        'source_namespace':'FONGIM','source_id':'664','status':'En cours',
        'end_date':'2026-11-30','title':'Selected'}}
    text, _ = answer('For FONGIM project ID 664, which active records have a reported end date in 2026?', [row])
    calls = []
    def research(question, **kwargs):
        calls.append(question)
        fresh = dict(row, project_record=dict(row['project_record'], status='Closed'))
        output, audit = answer(question, [fresh])
        assert audit['active_only'] and audit['matching_ids'] == []
        return {'answer':output, 'evidence':[fresh]}
    def forbidden(*args, **kwargs):
        raise AssertionError('No model rewrite needed for a bounded active date filter')
    engine = SimpleNamespace(generate_grounded_answer=research,
        is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=lambda *args:True,
        resolve_conversational_question=forbidden,
        source_inventory_answer=lambda:'', openai_client=None)
    with TestClient(web_api.app, base_url='http://127.0.0.1:8765') as client:
        with patch.dict(sys.modules, {'analysis_core':engine}):
            response = client.post('/api/chat', json={
                'question':'Which of those projects have a reported end date in 2026?',
                'prior_messages':[{'role':'assistant','content':text}]},
                headers={'Origin':'http://127.0.0.1:8765'})
    assert response.status_code == 200 and len(calls) == 1
    result = response.json()
    assert '**0 of 1' in result['answer']
    assert result['metrics']['context_resolution_method'] == 'structured_query_slots'
    assert result['metrics']['context_api_usage'] == {}
    assert result['evidence'][0]['content'] == 'Fresh source record'


@pytest.mark.parametrize('language,question,marker,expected', [
    ('English', 'Which of those projects have a reported end date in 2026?',
     'Selected source identifiers for this filter: none.', 'current project subset is empty'),
    ('French', 'Lesquels de ces projets ont une date de fin en 2026 ?',
     'Identifiants source sélectionnés par ce filtre : aucun.', 'sous-ensemble actuel de projets est vide'),
])
def test_empty_date_subset_remains_empty_without_carrying_prior_facts(
        language, question, marker, expected):
    from datetime import date
    from project_date_answers import answer
    rows = [
        {'evidence_id':'E01', 'project_record':{'source_namespace':'FONGIM',
         'source_id':'664', 'end_date':'2026-11-30', 'status':'En cours', 'title':'A'}},
        {'evidence_id':'E02', 'project_record':{'source_namespace':'FONGIM',
         'source_id':'32', 'end_date':'2027-01-01', 'status':'En cours', 'title':'B'}},
    ]
    previous = ('Pour FONGIM, identifiants de projets 664, 32, quels dossiers ont une date de fin déclarée en 2025 ?'
                if language == 'French' else
                'For FONGIM project IDs 664 and 32, which records have a reported end date in 2025?')
    text, audit = answer(previous, rows, language=language, asof=date(2026,10,9))
    assert audit['matching_ids'] == [] and marker in text
    resolved = resolve_slots(question, [{'role':'assistant','content':text}])
    assert resolved['method'] == 'structured_empty_project_subset'
    assert resolved['state']['lookup_ids'] == []
    assert expected in resolved['direct_answer']
    assert '2026-11-30' not in resolved['direct_answer']
    assert '2027-01-01' not in resolved['direct_answer']
    assert '664' not in resolved['direct_answer'] and '32' not in resolved['direct_answer']


def test_empty_subset_api_skips_semantic_rewrite_and_research():
    from project_date_answers import answer
    row = {'evidence_id':'E01','content':'Fresh source record', 'project_record':{
        'source_namespace':'FONGIM','source_id':'664','status':'En cours',
        'end_date':'2026-11-30','title':'Selected'}}
    text, _ = answer('For FONGIM project ID 664, which records have a reported end date in 2025?', [row])
    def forbidden(*args, **kwargs):
        raise AssertionError('An empty selected subset needs no model or source lookup')
    engine = SimpleNamespace(generate_grounded_answer=forbidden,
        is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=forbidden,
        resolve_conversational_question=forbidden,
        source_inventory_answer=lambda:'', openai_client=None)
    with TestClient(web_api.app, base_url='http://127.0.0.1:8765') as client:
        with patch.dict(sys.modules, {'analysis_core':engine}):
            response = client.post('/api/chat', json={
                'question':'Which of those projects have a reported end date in 2026?',
                'prior_messages':[{'role':'assistant','content':text}]},
                headers={'Origin':'http://127.0.0.1:8765'})
    assert response.status_code == 200
    result = response.json()
    assert result['metrics']['context_resolution_method'] == 'structured_empty_project_subset'
    assert result['metrics']['model_calls'] == 0
    assert result['metrics']['external_research_calls'] == 0
    assert result['evidence'] == []
    assert 'current project subset is empty' in result['answer']


@pytest.mark.parametrize('question,source,expected,excluded', [
    ('Which of those FONGIM projects have a reported end date in 2026?',
     'FONGIM', [32, 664], ['P164032', 'P513735', 'XI-IATI-EC_INTPA-2023-PC-34274']),
    ('Which of those World Bank projects end in 2027?',
     'World Bank', ['P164032', 'P513735'], ['XI-IATI-EC_INTPA-2023-PC-34274']),
    ('Which of those EU projects have a reported closing date in 2026?',
     'EU IATI', ['XI-IATI-EC_INTPA-2023-PC-34274'], ['32', '664', 'P164032', 'P513735']),
    ('Lesquels de ces projets FONGIM ont une date de fin en 2026 ?',
     'FONGIM', [32, 664], ['P164032', 'P513735', 'XI-IATI-EC_INTPA-2023-PC-34274']),
    ('Lesquels de ces projets de la Banque mondiale ont une date de fin en 2027 ?',
     'World Bank', ['P164032', 'P513735'], ['XI-IATI-EC_INTPA-2023-PC-34274']),
    ("Lesquels de ces projets de l'UE ont une date de clôture en 2026 ?",
     'EU IATI', ['XI-IATI-EC_INTPA-2023-PC-34274'], ['32', '664', 'P164032', 'P513735']),
])
def test_explicit_source_disambiguates_mixed_project_roster(
        question, source, expected, excluded):
    mixed = ('FONGIM records: Project ID 664; Project ID 32. '
             'World Bank records: P513735 and P164032. '
             'EU records: XI-IATI-EC_INTPA-2023-PC-34274. '
             'All allegedly ended in 2099 and reached 999 people.')
    result = resolve_slots(question, [{'role':'assistant', 'content':mixed}])
    assert result['state']['source'] == source
    assert result['state']['lookup_ids'] == expected
    assert result['state']['context_only']
    assert all(value not in result['standalone_question'] for value in excluded)
    assert '2099' not in result['standalone_question']
    assert '999' not in result['standalone_question']


@pytest.mark.parametrize('question', [
    'Which of those projects have a reported end date in 2026?',
    'Which of those projects have a reported end date between 2026-11-01 and 2026-12-31?',
])
def test_mixed_roster_without_explicit_source_remains_ambiguous(question):
    mixed = 'FONGIM records: Project ID 664. World Bank records: P513735.'
    assert resolve_slots(question, [{'role':'assistant', 'content':mixed}]) is None


def test_mixed_roster_explicit_source_api_retrieves_freshly_without_rewrite():
    calls = []
    mixed = ('FONGIM records: Project ID 664; Project ID 32. '
             'World Bank records: P513735 and P164032. All ended in 2099.')
    def research(question, **kwargs):
        calls.append(question)
        assert 'FONGIM' in question and '32, 664' in question
        assert 'P513735' not in question and 'P164032' not in question
        assert '2099' not in question
        return {'answer':'Fresh FONGIM lookup [E01]', 'evidence':[
            {'evidence_id':'E01', 'content':'Fresh source record'}]}
    def forbidden(*args, **kwargs):
        raise AssertionError('An explicitly named source needs no semantic rewrite')
    engine = SimpleNamespace(generate_grounded_answer=research,
        is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=lambda *args:True,
        resolve_conversational_question=forbidden,
        source_inventory_answer=lambda:'', openai_client=None)
    with TestClient(web_api.app, base_url='http://127.0.0.1:8765') as client:
        with patch.dict(sys.modules, {'analysis_core':engine}):
            response = client.post('/api/chat', json={
                'question':'Which of those FONGIM projects have a reported end date in 2026?',
                'prior_messages':[{'role':'assistant', 'content':mixed}]},
                headers={'Origin':'http://127.0.0.1:8765'})
    assert response.status_code == 200 and len(calls) == 1
    body = response.json()
    assert body['metrics']['context_resolution_method'] == 'structured_query_slots'
    assert body['metrics']['context_api_usage'] == {}
    assert body['evidence'][0]['content'] == 'Fresh source record'


def test_mixed_roster_explicit_source_range_api_retrieves_freshly_without_rewrite():
    from project_dates import reported_end_window
    from project_references import fongim_project_ids
    calls = []
    mixed = ('FONGIM records: Project ID 664; Project ID 32. '
             'World Bank records: P513735 and P164032. End date 2099-12-31.')
    question = ('Which of those World Bank projects have a reported end date '
                'between 2026-11-01 and 2027-01-31?')
    def research(standalone, **kwargs):
        calls.append(standalone)
        assert 'World Bank' in standalone and 'P164032, P513735' in standalone
        assert fongim_project_ids(standalone) == ()
        assert '2099' not in standalone
        assert reported_end_window(standalone) == ('2026-11-01', '2027-01-31')
        return {'answer':'Fresh World Bank lookup [E01]', 'evidence':[
            {'evidence_id':'E01', 'content':'Fresh source record'}]}
    def forbidden(*args, **kwargs):
        raise AssertionError('An explicit source range needs no semantic rewrite')
    engine = SimpleNamespace(generate_grounded_answer=research,
        is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=lambda *args:True,
        resolve_conversational_question=forbidden,
        source_inventory_answer=lambda:'', openai_client=None)
    with TestClient(web_api.app, base_url='http://127.0.0.1:8765') as client:
        with patch.dict(sys.modules, {'analysis_core':engine}):
            response = client.post('/api/chat', json={
                'question':question,
                'prior_messages':[{'role':'assistant', 'content':mixed}]},
                headers={'Origin':'http://127.0.0.1:8765'})
    assert response.status_code == 200 and len(calls) == 1
    body = response.json()
    assert body['metrics']['context_resolution_method'] == 'structured_query_slots'
    assert body['metrics']['context_api_usage'] == {}
    assert body['evidence'][0]['content'] == 'Fresh source record'


@pytest.mark.parametrize('roster,question,source,ids', [
    ('FONGIM project ID 32; Project ID 664.',
     'Which of those projects have a reported end date next year?',
     'FONGIM', [32, 664]),
    ('World Bank P144442 and P176347.',
     'Which of them are ending next year?',
     'World Bank', ['P144442', 'P176347']),
    ('EU XI-IATI-EC_INTPA-2023-PC-34274.',
     'Lesquels de ces projets ont une date de fin l’année prochaine ?',
     'EU IATI', ['XI-IATI-EC_INTPA-2023-PC-34274']),
    ('FONGIM project ID 664.',
     'Lesquels de ces projets ont une date de clôture l’an prochain ?',
     'FONGIM', [664]),
])
def test_next_calendar_year_followups_keep_ids_and_freeze_year(
        roster, question, source, ids):
    from datetime import datetime, timezone
    result = resolve_slots(question, [{'role':'assistant', 'content':
        roster + ' End date 2099-12-31; reported reach 999.'}])
    expected_year = str(datetime.now(timezone.utc).year + 1)
    assert result['state']['source'] == source
    assert result['state']['lookup_ids'] == ids
    assert result['state']['time_period'] == [expected_year]
    assert expected_year in result['standalone_question']
    assert 'next year' not in result['standalone_question'].lower()
    assert 'prochain' not in result['standalone_question'].lower()
    assert '2099' not in result['standalone_question']
    assert '999' not in result['standalone_question']


def test_next_calendar_year_preserves_active_only_and_named_mixed_source():
    from project_date_answers import answer
    row = {'evidence_id':'E01', 'project_record':{'source_namespace':'World Bank',
        'source_id':'P513735', 'status':'Active', 'end_date':'2026-11-30',
        'title':'Selected'}}
    active_table, _ = answer(
        'For World Bank project IDs P513735, which active records have a reported end date in 2026?',
        [row])
    active = resolve_slots('Which of those projects end next year?',
                           [{'role':'assistant', 'content':active_table}])
    assert active['state']['active_only'] is True
    assert active['state']['lookup_ids'] == ['P513735']
    assert 'active records' in active['standalone_question']

    mixed = ('FONGIM project ID 664. World Bank P513735 and P164032. '
             'EU XI-IATI-EC_INTPA-2023-PC-34274.')
    selected = resolve_slots('Which of those World Bank projects end next year?',
                             [{'role':'assistant', 'content':mixed}])
    assert selected['state']['source'] == 'World Bank'
    assert selected['state']['lookup_ids'] == ['P164032', 'P513735']
    assert '664' not in selected['standalone_question']
    assert 'XI-IATI' not in selected['standalone_question']


@pytest.mark.parametrize('question', [
    'Which of those projects end this year or next year?',
    'Which of those projects end in 2028 or next year?',
    'Which of those projects end in the next 3 months or next year?',
    'Lesquels de ces projets ont une date de fin cette année ou l’année prochaine ?',
])
def test_compound_next_year_followups_defer(question):
    assert resolve_slots(question, [{'role':'assistant', 'content':
        'FONGIM project ID 664.'}]) is None


def test_next_calendar_year_api_retrieves_freshly_without_rewrite():
    from datetime import datetime, timezone
    calls = []
    expected_year = str(datetime.now(timezone.utc).year + 1)
    def research(question, **kwargs):
        calls.append(question)
        assert 'FONGIM' in question and '32, 664' in question
        assert expected_year in question and '2099' not in question
        return {'answer':'Fresh next-year lookup [E01]', 'evidence':[
            {'evidence_id':'E01', 'content':'Fresh source record'}]}
    def forbidden(*args, **kwargs):
        raise AssertionError('A bounded next-calendar-year filter needs no semantic rewrite')
    engine = SimpleNamespace(generate_grounded_answer=research,
        is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=lambda *args:True,
        resolve_conversational_question=forbidden,
        source_inventory_answer=lambda:'', openai_client=None)
    with TestClient(web_api.app, base_url='http://127.0.0.1:8765') as client:
        with patch.dict(sys.modules, {'analysis_core':engine}):
            response = client.post('/api/chat', json={
                'question':'Which of those projects end next year?',
                'prior_messages':[{'role':'assistant', 'content':
                    'FONGIM project ID 32; Project ID 664. All ended in 2099.'}]},
                headers={'Origin':'http://127.0.0.1:8765'})
    assert response.status_code == 200 and len(calls) == 1
    body = response.json()
    assert body['metrics']['context_resolution_method'] == 'structured_query_slots'
    assert body['metrics']['context_api_usage'] == {}
    assert body['evidence'][0]['content'] == 'Fresh source record'


@pytest.mark.parametrize('roster,question,source,ids', [
    ('FONGIM project ID 32; Project ID 664.',
     'Lesquels de ces projets ont une date de fin cette année ?',
     'FONGIM', [32, 664]),
    ('World Bank P144442 and P176347.',
     'Lesquels de ces projets ont une date de clôture cette année ?',
     'World Bank', ['P144442', 'P176347']),
    ('EU XI-IATI-EC_INTPA-2023-PC-34274.',
     'Lesquels de ces projets ont une date de fin cette année ?',
     'EU IATI', ['XI-IATI-EC_INTPA-2023-PC-34274']),
])
def test_french_current_calendar_year_followups_keep_ids_and_freeze_year(
        roster, question, source, ids):
    from datetime import datetime, timezone
    result = resolve_slots(question, [{'role':'assistant', 'content':
        roster + ' End date 2099-12-31; reported reach 999.'}])
    expected_year = str(datetime.now(timezone.utc).year)
    assert result['state']['source'] == source
    assert result['state']['lookup_ids'] == ids
    assert result['state']['time_period'] == [expected_year]
    assert result['standalone_question'].endswith(f'en {expected_year} ?')
    assert 'cette année' not in result['standalone_question'].lower()
    assert '2099' not in result['standalone_question']
    assert '999' not in result['standalone_question']


def test_french_current_calendar_year_preserves_active_only_and_named_mixed_source():
    from project_date_answers import answer
    row = {'evidence_id':'E01', 'project_record':{'source_namespace':'World Bank',
        'source_id':'P513735', 'status':'Active', 'end_date':'2026-11-30',
        'title':'Selected'}}
    active_table, _ = answer(
        'For World Bank project IDs P513735, which active records have a reported end date in 2026?',
        [row])
    active = resolve_slots(
        'Lesquels de ces projets ont une date de fin cette année ?',
        [{'role':'assistant', 'content':active_table}])
    assert active['state']['active_only'] is True
    assert active['state']['lookup_ids'] == ['P513735']
    assert 'dossiers actifs' in active['standalone_question']

    mixed = ('FONGIM project ID 664. World Bank P513735 and P164032. '
             'EU XI-IATI-EC_INTPA-2023-PC-34274.')
    selected = resolve_slots(
        'Lesquels de ces projets de la Banque mondiale ont une date de fin cette année ?',
        [{'role':'assistant', 'content':mixed}])
    assert selected['state']['source'] == 'World Bank'
    assert selected['state']['lookup_ids'] == ['P164032', 'P513735']
    assert '664' not in selected['standalone_question']
    assert 'XI-IATI' not in selected['standalone_question']


@pytest.mark.parametrize('roster,question,source,ids', [
    ('FONGIM project ID 32; Project ID 664.',
     'Lesquels d’entre eux ont une date de fin en 2026 ?',
     'FONGIM', [32, 664]),
    ('World Bank P144442 and P176347.',
     "Lesquels d'entre eux ont une date de clôture dans les 3 prochains mois ?",
     'World Bank', ['P144442', 'P176347']),
    ('EU XI-IATI-EC_INTPA-2023-PC-34274.',
     'Lesquels parmi eux ont une date de fin cette année ?',
     'EU IATI', ['XI-IATI-EC_INTPA-2023-PC-34274']),
])
def test_french_pronoun_date_followups_keep_ids_and_fresh_period(
        roster, question, source, ids):
    result = resolve_slots(question, [{'role':'assistant', 'content':
        roster + ' End date 2099-12-31; reported reach 999.'}])
    assert result['state']['source'] == source
    assert result['state']['lookup_ids'] == ids
    assert '2099' not in result['standalone_question']
    assert '999' not in result['standalone_question']


def test_french_pronoun_followup_preserves_active_only_but_defers_analysis():
    from project_date_answers import answer
    row = {'evidence_id':'E01', 'project_record':{'source_namespace':'FONGIM',
        'source_id':'664', 'status':'En cours', 'end_date':'2026-11-30',
        'title':'Selected'}}
    active_table, _ = answer(
        'For FONGIM project ID 664, which active records have a reported end date in 2026?',
        [row], language='French')
    active = resolve_slots(
        'Lesquels d’entre eux ont une date de fin en 2027 ?',
        [{'role':'assistant', 'content':active_table}])
    assert active['state']['active_only'] is True
    assert active['state']['lookup_ids'] == [664]
    assert 'dossiers actifs' in active['standalone_question']
    assert resolve_slots(
        'Lesquels d’entre eux ont une date de fin en 2027 et couvrent les besoins ?',
        [{'role':'assistant', 'content':active_table}]) is None


def test_french_pronoun_followup_api_retrieves_once_without_rewrite():
    calls = []
    def research(question, **kwargs):
        calls.append(question)
        assert 'FONGIM' in question and '32, 664' in question
        assert '2026' in question and '2099' not in question
        return {'answer':'Fresh pronoun lookup [E01]', 'evidence':[
            {'evidence_id':'E01', 'content':'Fresh source record'}]}
    def forbidden(*args, **kwargs):
        raise AssertionError('A bounded French project pronoun needs no semantic rewrite')
    engine = SimpleNamespace(generate_grounded_answer=research,
        is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=lambda *args:True,
        resolve_conversational_question=forbidden,
        source_inventory_answer=lambda:'', openai_client=None)
    with TestClient(web_api.app, base_url='http://127.0.0.1:8765') as client:
        with patch.dict(sys.modules, {'analysis_core':engine}):
            response = client.post('/api/chat', json={
                'question':'Lesquels d’entre eux ont une date de fin en 2026 ?',
                'prior_messages':[{'role':'assistant', 'content':
                    'FONGIM project ID 32; Project ID 664. All ended in 2099.'}]},
                headers={'Origin':'http://127.0.0.1:8765'})
    assert response.status_code == 200 and len(calls) == 1
    body = response.json()
    assert body['metrics']['context_resolution_method'] == 'structured_query_slots'
    assert body['metrics']['context_api_usage'] == {}
    assert body['evidence'][0]['content'] == 'Fresh source record'


@pytest.mark.parametrize('roster,question,source,ids', [
    ('FONGIM project ID 32; Project ID 664.',
     'Which of those projects end this month?', 'FONGIM', [32, 664]),
    ('World Bank P144442 and P176347.',
     'Which of them have reported closing dates this month?',
     'World Bank', ['P144442', 'P176347']),
    ('EU XI-IATI-EC_INTPA-2023-PC-34274.',
     'Lesquels d’entre eux ont une date de fin ce mois-ci ?',
     'EU IATI', ['XI-IATI-EC_INTPA-2023-PC-34274']),
])
def test_current_calendar_month_followups_keep_ids_and_freeze_window(
        roster, question, source, ids):
    import calendar
    from datetime import datetime, timezone
    result = resolve_slots(question, [{'role':'assistant', 'content':
        roster + ' End date 2099-12-31; reported reach 999.'}])
    now = datetime.now(timezone.utc).date()
    expected_start = now.replace(day=1).isoformat()
    expected_end = now.replace(day=calendar.monthrange(now.year, now.month)[1]).isoformat()
    assert result['state']['source'] == source
    assert result['state']['lookup_ids'] == ids
    assert result['state']['time_period'] == [expected_start, expected_end]
    assert result['standalone_question'].endswith(
        (f'entre {expected_start} et {expected_end} ?' if question.startswith('Lesquels')
         else f'between {expected_start} and {expected_end}?'))
    assert '2099' not in result['standalone_question']
    assert '999' not in result['standalone_question']


def test_calendar_month_followup_preserves_active_only_and_defers_compounds():
    from project_date_answers import answer
    row = {'evidence_id':'E01', 'project_record':{'source_namespace':'FONGIM',
        'source_id':'664', 'status':'En cours', 'end_date':'2026-10-30',
        'title':'Selected'}}
    active_table, _ = answer(
        'For FONGIM project ID 664, which active records have a reported end date in 2026?',
        [row], language='French')
    active = resolve_slots(
        'Lesquels parmi eux ont une date de fin ce mois-ci ?',
        [{'role':'assistant', 'content':active_table}])
    assert active['state']['active_only'] is True
    assert active['state']['lookup_ids'] == [664]
    assert 'dossiers actifs' in active['standalone_question']
    assert resolve_slots(
        'Lesquels parmi eux ont une date de fin ce mois-ci ou l’année prochaine ?',
        [{'role':'assistant', 'content':active_table}]) is None


def test_calendar_month_followup_api_retrieves_once_without_rewrite():
    calls = []
    def research(question, **kwargs):
        calls.append(question)
        assert 'FONGIM' in question and '32, 664' in question
        assert '2099' not in question and 'between ' in question
        return {'answer':'Fresh calendar-month lookup [E01]', 'evidence':[
            {'evidence_id':'E01', 'content':'Fresh source record'}]}
    def forbidden(*args, **kwargs):
        raise AssertionError('A bounded calendar-month filter needs no semantic rewrite')
    engine = SimpleNamespace(generate_grounded_answer=research,
        is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=lambda *args:True,
        resolve_conversational_question=forbidden,
        source_inventory_answer=lambda:'', openai_client=None)
    with TestClient(web_api.app, base_url='http://127.0.0.1:8765') as client:
        with patch.dict(sys.modules, {'analysis_core':engine}):
            response = client.post('/api/chat', json={
                'question':'Which of those projects end this month?',
                'prior_messages':[{'role':'assistant', 'content':
                    'FONGIM project ID 32; Project ID 664. All ended in 2099.'}]},
                headers={'Origin':'http://127.0.0.1:8765'})
    assert response.status_code == 200 and len(calls) == 1
    body = response.json()
    assert body['metrics']['context_resolution_method'] == 'structured_query_slots'
    assert body['metrics']['context_api_usage'] == {}
    assert body['evidence'][0]['content'] == 'Fresh source record'


def test_french_current_calendar_year_api_retrieves_freshly_without_rewrite():
    from datetime import datetime, timezone
    calls = []
    expected_year = str(datetime.now(timezone.utc).year)
    def research(question, **kwargs):
        calls.append(question)
        assert 'FONGIM' in question and '32, 664' in question
        assert expected_year in question and '2099' not in question
        return {'answer':'Fresh current-year lookup [E01]', 'evidence':[
            {'evidence_id':'E01', 'content':'Fresh source record'}]}
    def forbidden(*args, **kwargs):
        raise AssertionError('A bounded current-calendar-year filter needs no semantic rewrite')
    engine = SimpleNamespace(generate_grounded_answer=research,
        is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=lambda *args:True,
        resolve_conversational_question=forbidden,
        source_inventory_answer=lambda:'', openai_client=None)
    with TestClient(web_api.app, base_url='http://127.0.0.1:8765') as client:
        with patch.dict(sys.modules, {'analysis_core':engine}):
            response = client.post('/api/chat', json={
                'question':'Lesquels de ces projets ont une date de fin cette année ?',
                'prior_messages':[{'role':'assistant', 'content':
                    'FONGIM project ID 32; Project ID 664. All ended in 2099.'}]},
                headers={'Origin':'http://127.0.0.1:8765'})
    assert response.status_code == 200 and len(calls) == 1
    body = response.json()
    assert body['metrics']['context_resolution_method'] == 'structured_query_slots'
    assert body['metrics']['context_api_usage'] == {}
    assert body['evidence'][0]['content'] == 'Fresh source record'
