import pytest
from evaluation.cohorts import summarize


def test_incorrect_fast_route_and_failure_remain_in_complex_cohort():
    cases={'JOIN02': {'difficulty':'deep', 'category':'joined_analysis'},
           'GEO01': {'difficulty':'quick', 'category':'geography'}}
    def attempt(cid, rep, ok, seconds, route):
        return {'case_id':cid, 'repetition':rep, 'ok':ok, 'client_seconds':seconds,
                'telemetry':{'route':route, 'server_seconds':seconds if ok else None,
                             'input_tokens':10 if ok else None, 'output_tokens':2 if ok else None,
                             'estimated_usd':.01 if ok else None,
                             'model_calls':[{'endpoint':'responses'}] if ok else []}}
    rows=[attempt('JOIN02',0,True,5,'simple_geography'),
          attempt('JOIN02',1,False,100,None), attempt('JOIN02',2,True,15,'deep_research'),
          attempt('GEO01',0,True,.01,'simple_geography')]
    cohorts=summarize(rows,cases,[])['cohorts']
    assert cohorts['complex']['attempts']==3 and cohorts['complex']['failures']==1
    assert cohorts['complex']['client_attempt_latency_seconds']['p95']==pytest.approx(91.5)
    assert cohorts['complex']['server_success_latency_seconds']['median']==10
    assert cohorts['complex']['input_tokens']['total']==20
    assert cohorts['complex']['cost_unknown_attempts']==1
    assert cohorts['case/JOIN02']==cohorts['complex']
