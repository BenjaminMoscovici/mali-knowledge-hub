from evaluation.common import write_json,digest
from evaluation.judge_integrity import inspect


def test_fabricated_region_quote_is_visible_without_changing_quality_scores(tmp_path):
    answer='Mali (country) → **MOPTI** (region) → KONNA (cercle) → KONNA (commune). [E01]'
    response={'answer':answer};raw={'ok':True,'response':response,'response_hash':digest(response)}
    judgment={'response_hash':raw['response_hash'],'result':{
        'claims':[{'text':'KONNA (region)','verdict':'contradicted'},
                  {'text':'MOPTI (region)','verdict':'unsupported'}], 'findings':[]}}
    write_json(tmp_path/'raw/C05--1.json',raw);write_json(tmp_path/'judgments/C05--1.json',judgment)
    before=(tmp_path/'judgments/C05--1.json').read_bytes();report=inspect(tmp_path)
    assert report['checked_quotes']==2 and report['nonliteral_quotes']==1
    assert report['flags'][0]['returned_quote']=='KONNA (region)'
    assert report['score_override'] is False
    assert (tmp_path/'judgments/C05--1.json').read_bytes()==before
