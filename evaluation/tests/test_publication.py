import subprocess
from copy import deepcopy
from evaluation.publication import proof,verified

def test_actual_runtime_and_build_bytes_required_despite_claimed_equivalence(tmp_path):
    def git(*args):return subprocess.check_output(['git','-C',str(tmp_path),*args],text=True).strip()
    git('init','-q');git('config','user.email','test@example.invalid');git('config','user.name','Synthetic Test')
    (tmp_path/'v3').mkdir();(tmp_path/'v3/app.py').write_text('value=1\n')
    (tmp_path/'requirements.txt').write_text('dependency==1\n')
    git('add','.');git('commit','-qm','Measured runtime');measured=git('rev-parse','HEAD')
    (tmp_path/'README.md').write_text('Publication-only change\n')
    git('add','.');git('commit','-qm','Browser publication');published=git('rev-parse','HEAD')
    receipt=proof(measured,published,tmp_path)
    assert verified(measured,published,receipt,tmp_path)
    forged=deepcopy(receipt);forged['repository']='unrelated/repository'
    assert not verified(measured,published,forged,tmp_path)
    forged=deepcopy(receipt);forged['published_fingerprint']['runtime_v3_tree_sha']='a'*40
    assert not verified(measured,published,forged,tmp_path)
    for path,content in [('v3/app.py','value=2\n'),('requirements.txt','dependency==2\n')]:
        (tmp_path/path).write_text(content);git('add','.');git('commit','-qm','Changed deployed bytes')
        changed=git('rev-parse','HEAD');bad=proof(measured,changed,tmp_path);bad['byte_equivalent']=True
        assert not verified(measured,changed,bad,tmp_path)
    assert not verified(measured,'missing',receipt,tmp_path)
