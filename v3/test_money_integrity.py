from money_integrity import amounts, validate


def test_french_original_currency_and_english_million_normalize():
    assert amounts('577,9 millions USD')[0]['amount'] == amounts('USD 577.9 million')[0]['amount']
    assert amounts('EUR 32 million')[0]['amount'] == amounts('€32m')[0]['amount']


def test_wrong_currency_caught_without_converting_or_changing_citations():
    evidence = [{'evidence_id':'E04','content':'HNRP : 577,9 millions USD.'},
                {'evidence_id':'E02','content':'ECHO allocation EUR 32 million.'}]
    audit = validate('HNRP requests €577.9m and ECHO allocates EUR 32 million [E04, E02].', evidence)
    assert not audit['valid']
    assert audit['explicit_pair_mismatches'][0]['source_currencies'] == ['USD']
    assert len(audit['checked_pairs']) == 1


def test_unknown_pairs_and_legitimate_equal_amount_currencies_not_false_failures():
    e=[{'evidence_id':'E01','content':'USD 10 million.'},{'evidence_id':'E02','content':'EUR 10 million.'}]
    a=validate('EUR 10 million [E01, E02].\n\nUSD 55 million [E01].',e)
    assert a['valid'] and len(a['unassessed_pairs']) == 1
    assert amounts('USD 1,234') == []


def test_uncited_neighbor_paragraph_cannot_supply_a_currency_witness():
    e=[{'evidence_id':'E01','content':'USD 42 million.'},{'evidence_id':'E02','content':'EUR 42 million.'}]
    a=validate('EUR 42 million [E01].\n\nOther record [E02].',e)
    assert not a['valid']


def test_explicit_correction_of_wrong_currency_is_not_blocked():
    e=[{'evidence_id':'E01','content':'577,9 millions USD.'}]
    a=validate('It is not EUR 577.9 million, but USD 577.9 million [E01].',e)
    assert a['valid'] and len(a['checked_pairs']) == 1
    assert validate('The label "EUR 577.9 million" is incorrect. USD 577.9 million [E01].',e)['valid']


def test_synthesis_withholds_explicit_currency_error_without_an_extra_model_pass():
    from datetime import datetime, timezone
    import ast
    import re
    import time
    from pathlib import Path
    from types import SimpleNamespace
    from citations import verify
    from synthesis_context import prepare, serialize, availability_note
    tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_generate_grounded_answer')
    drafts=['Reported amount: EUR 42 million [E01].','Reported amount: USD 42 million [E01].']
    calls=[]
    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text=drafts.pop(0))
    def research(*args,**kwargs):
        return {'ledger':[{'evidence_id':'E01','source_type':'structured_data','source_family':'Funding',
                           'content':'Reported amount: USD 42 million.','record_id':'funding-42','locator':'row 1'}],
                'geography':{},'joined':{},'execution_trace':{},'source_plan':{},'family_counts':{},
                'hapi_raw_count':0,'fongim_project_count':0,'research_seconds':0}
    ns={'re':re,'time':time,'datetime':datetime,'timezone':timezone,'PHASE':SimpleNamespace(set=lambda _:None),
        'get_mode':lambda _:{'document_count':1,'max_output_tokens':1800},
        'run_four_source_research':research,'prepare_synthesis':prepare,'serialize_synthesis':serialize,
        'build_join_context':lambda *a:{},'prompt_context':lambda _:'',
        'intersectoral_locality_note':lambda _:'','availability_note':availability_note,
        'preserve_project_identifiers':lambda text,ledger,question:text,
        'answer_language':lambda _:'English','verify_citations':verify,'validate_money':validate,
        'openai_client':SimpleNamespace(responses=SimpleNamespace(create=generate))}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'isolated-synthesis-guard','exec'),ns)
    bad=ns['_generate_grounded_answer']('What are the reported amounts?')
    assert 'withheld' in bad['answer'] and len(calls)==1
    audit=bad['execution_trace']['synthesis_context']['money_integrity']
    assert not audit['valid'] and audit['explicit_pair_mismatches']
    good=ns['_generate_grounded_answer']('What are the reported amounts?')
    assert good['answer']=='Reported amount: USD 42 million [E01].' and len(calls)==2


def test_omitted_source_citation_gets_one_grounded_regeneration_but_invented_ids_do_not():
    from datetime import datetime, timezone
    import ast,re,time
    from pathlib import Path
    from types import SimpleNamespace
    from citations import verify
    from synthesis_context import serialize,availability_note
    function=next(n for n in ast.parse(Path(__file__).with_name('analysis_core.py').read_text()).body
                  if isinstance(n,ast.FunctionDef) and n.name=='_generate_grounded_answer')
    for drafts,expected_calls,withheld in [
        (['Amount USD 42 million [E05].','Amount USD 42 million [E05].'],2,False),
        (['Invented reference [E99].'],1,True),
        (['Amount USD 42 million [E05].','Invented reference [E99].'],2,True),
        (['Amount USD 42 million [E05].','Amount EUR 42 million [E05].'],2,True)]:
        calls=[];remaining=list(drafts)
        def generate(**kwargs):
            calls.append(kwargs);return SimpleNamespace(output_text=remaining.pop(0))
        ledger=[{'evidence_id':'E01','content':'Different source context.','source_type':'structured_data'},
                {'evidence_id':'E05','content':'Amount USD 42 million.','source_type':'knowledge_base_document'}]
        def research(*a,**k):
            return {'ledger':ledger,'geography':{},'joined':{},'execution_trace':{},'source_plan':{},
                    'family_counts':{},'hapi_raw_count':0,'fongim_project_count':0,'research_seconds':0}
        ns={'re':re,'time':time,'datetime':datetime,'timezone':timezone,'PHASE':SimpleNamespace(set=lambda _:None),
            'get_mode':lambda _:{'document_count':1,'max_output_tokens':1800},
            'run_four_source_research':research,
            'prepare_synthesis':lambda *a:([ledger[0]],{'omitted_ids':['E05'],'synthesis_items':1}),
            'serialize_synthesis':serialize,'build_join_context':lambda *a:{},'prompt_context':lambda _:'',
            'intersectoral_locality_note':lambda _:'','availability_note':availability_note,
            'preserve_project_identifiers':lambda text,ledger,question:text,
            'answer_language':lambda _:'English','verify_citations':verify,'validate_money':validate,
            'openai_client':SimpleNamespace(responses=SimpleNamespace(create=generate))}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'citation-source-repair','exec'),ns)
        result=ns['_generate_grounded_answer']('What amount is reported?')
        assert len(calls)==expected_calls
        assert ('withheld' in result['answer'] or 'could not verify' in result['answer'])==withheld
        if expected_calls==2:
            assert 'Amount USD 42 million.' in calls[1]['input']
            assert '[E05]' in calls[1]['input'].split('PERMITTED CITATION IDS',1)[1].split('\n',1)[0]
            audit=result['execution_trace']['synthesis_context']
            assert audit['citation_repair_added_ids']==['E05']
        assert ledger[1]['evidence_id']=='E05'
