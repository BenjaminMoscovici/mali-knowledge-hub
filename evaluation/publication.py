"""Bind browser-published commit identities to actual measured runtime bytes."""
import re
import subprocess
from pathlib import Path
from .common import ROOT, now

BUILD_FILES=('Dockerfile','requirements.txt','.python-version','render.yaml')
REPOSITORY='BenjaminMoscovici/mali-knowledge-hub'

def git(repo,*args):
    return subprocess.check_output(['git','-C',str(repo),*args],text=True,stderr=subprocess.DEVNULL).strip()

def fingerprint(repo,commit):
    if not re.fullmatch(r'[0-9a-f]{40}',str(commit)):
        raise ValueError('An immutable full commit SHA is required')
    assert git(repo,'rev-parse',commit)==commit
    files={}
    for name in BUILD_FILES:
        try:files[name]=git(repo,'rev-parse','--verify',commit+':'+name)
        except subprocess.CalledProcessError:files[name]=None
    return {'runtime_v3_tree_sha':git(repo,'rev-parse',commit+':v3'),'build_file_blobs':files}

def proof(measured,published,repo=ROOT):
    a,b=fingerprint(repo,measured),fingerprint(repo,published)
    return {'version':'runtime-publication-equivalence-1.0','repository':REPOSITORY,
            'measured_commit':measured,'published_commit':published,
            'measured_fingerprint':a,'published_fingerprint':b,
            'byte_equivalent':a==b,'verified_at':now(),
            'scope':'v3 runtime and root build/launch files; no inferred deployment, privacy or quality pass'}

def verified(measured,published,receipt,repo=ROOT):
    if not isinstance(receipt,dict) or receipt.get('repository')!=REPOSITORY:
        return False
    if receipt.get('measured_commit')!=measured or receipt.get('published_commit')!=published:
        return False
    try:
        actual=proof(measured,published,repo)
        return bool(actual['byte_equivalent'] and receipt.get('byte_equivalent') is True
                    and receipt.get('verified_at')
                    and receipt.get('measured_fingerprint')==actual['measured_fingerprint']
                    and receipt.get('published_fingerprint')==actual['published_fingerprint'])
    except (ValueError,AssertionError,subprocess.CalledProcessError):
        return False
