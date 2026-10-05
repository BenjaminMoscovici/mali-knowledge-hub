import json
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from evaluation.common import write_json
from evaluation.telemetry import import_isolated_failure,enriched


def test_failed_cost_receipt_requires_same_commit_and_exact_single_attempt():
    with TemporaryDirectory() as tmp:
        root=Path(tmp)
        record={'ok':False,'case_id':'JOIN03','repetition':0,'request_payload':{'analysis_mode':'deep'},'telemetry':{},'cost_unknown':True}
        write_json(root/'raw/JOIN03--0.json',record)
        write_json(root/'run_manifest.json',{'measurement_protocol':'isolated-asgi-guest-v1','hub_commit':'verified'})
        event={'request_id':'request-one','depth':'deep','error_type':'ReadTimeout','api_usage':{'calls':[{'endpoint':'embeddings','input_tokens':83,'output_tokens':0,'estimated_usd':.00000166}],'external_calls':[]}}
        log=root/'isolated.log'
        lines=[json.dumps({'isolated_health':200,'commit':'verified'}),'MKH_FAILURE '+json.dumps(event),json.dumps({'case':'JOIN03','repetition':0,'ok':False})]
        log.write_text('\n'.join(lines))
        import_isolated_failure(root,log)
        observed=enriched(root,record)
        assert observed['telemetry']['input_tokens']==83
        assert observed['telemetry']['estimated_usd']==.00000166
        assert observed['cost_unknown'] is True and record['telemetry']=={}
        changed=dict(record,case_id='OTHER')
        with pytest.raises(ValueError):enriched(root,changed)
        lines[0]=json.dumps({'isolated_health':200,'commit':'other'})
        log.write_text('\n'.join(lines))
        with pytest.raises(ValueError):import_isolated_failure(root,log)
        lines[0]=json.dumps({'isolated_health':200,'commit':'verified'});lines.append(lines[-1])
        log.write_text('\n'.join(lines))
        with pytest.raises(ValueError):import_isolated_failure(root,log)
