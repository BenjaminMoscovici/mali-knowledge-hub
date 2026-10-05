"""Opt-in release benchmark worker, restricted to the GIZ V4 test service.

No HTTP trigger, new credential, account-history access or public artifact route.
Original responses and judge receipts remain in private GIZ Storage; only
aggregate measurements are emitted to the service's existing private logs.
"""
import hashlib
import io
import json
import os
import re
import urllib.request
import urllib.error
import zipfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from .common import ROOT, config, digest, now, verify_freeze, write_json
from .runner import BASE, run

SERVICE = 'srv-davpdjugekts73ev4v3g'
PROJECT = 'https://hofoubbmepacdljeablj.supabase.co'
BUCKET = 'mkh-evaluations'
MAX_BYTES = 32 * 1024 * 1024


def authorized(env):
    label = env.get('MKH_EVALUATION_RUN', '')
    if not label:
        return False
    if env.get('RENDER_SERVICE_ID') != SERVICE or env.get('SUPABASE_URL', '').rstrip('/') != PROJECT:
        raise ValueError('Benchmark worker is restricted to the GIZ V4 test service')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', label):
        raise ValueError('Invalid benchmark milestone label')
    if not re.fullmatch(r'[0-9a-f]{40}', env.get('RENDER_GIT_COMMIT', '')):
        raise ValueError('An immutable deployed commit is required')
    return True


def private_storage(client):
    buckets = client.storage.list_buckets()
    existing = next((b for b in buckets if b.id == BUCKET), None)
    if existing is None:
        client.storage.create_bucket(BUCKET, options={'public': False,
            'allowed_mime_types': ['application/zip'], 'file_size_limit': MAX_BYTES})
        existing = client.storage.get_bucket(BUCKET)
    if existing.public is not False:
        raise ValueError('Evaluation artifact bucket must be private')
    return client.storage.from_(BUCKET)


def provenance(directory):
    """Reuse the baseline's public PDFs only when the exact bytes still match."""
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'evaluation/public_provenance.json').read_text())
    for doc in manifest['documents']:
        if doc['status'] != 'verified_public_download':
            continue
        try:
            with urllib.request.urlopen(doc['public_url'], timeout=45) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != doc['sha256']:
                raise ValueError('Public provenance changed or exceeded bound')
            import fitz
            with fitz.open(stream=raw, filetype='pdf') as pdf:
                pages = '\f'.join(page.get_text() for page in pdf)
            target = directory / (doc['document_id'] + '.txt')
            target.write_text(pages)
            doc['pages_file'] = str(target)
        except Exception as exc:
            doc['status'] = 'unverified'
            doc['error_type'] = type(exc).__name__
            doc.pop('pages_file', None)
    target = directory / 'manifest.json'; write_json(target, manifest)
    return target


def archive(directory, secrets):
    """Explicit artifact allowlist. Runtime configuration is never packaged."""
    directory = Path(directory); output = io.BytesIO()
    allowed_dirs = {'raw', 'judgments', 'judge_receipts', 'judge_packets',
                    'judge_errors', 'validation', 'release', 'public-provenance', 'exports'}
    allowed_files = {'run_manifest.json', 'scorecard.json', 'oracle.json', 'milestone.json'}
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(directory.rglob('*')):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(directory)
            if path.name not in allowed_files and not any(p in allowed_dirs for p in relative.parts[:-1]):
                continue
            if path.suffix not in {'.json', '.txt', '.svg', '.png', '.csv', '.html'}:
                continue
            data = path.read_bytes()
            if any(secret and secret.encode() in data for secret in secrets):
                raise ValueError('Credential found in evaluation artifact')
            zipped.writestr(str(relative), data)
    data = output.getvalue()
    if len(data) > MAX_BYTES:
        raise ValueError('Evaluation archive exceeds private bucket size bound')
    return data


def checkpoint(storage, directory, prefix, phase, secrets):
    if any(x.get('name') == phase + '.zip' for x in storage.list(prefix)):
        return
    data = archive(directory, secrets)
    name = f'{prefix}/{phase}.zip'
    storage.upload(name, data, {'content-type': 'application/zip', 'upsert': 'false'})
    objects = storage.list(prefix)
    if not any(x.get('name') == phase + '.zip' for x in objects):
        raise ValueError('Private artifact upload could not be verified')
    # Existence is confirmed through service-role storage above. Independently
    # check that the unauthenticated public object route cannot read it.
    try:
        with urllib.request.urlopen(PROJECT + '/storage/v1/object/public/' + BUCKET + '/' + name, timeout=20) as response:
            response.read(1)
        raise ValueError('Evaluation artifact unexpectedly readable anonymously')
    except urllib.error.HTTPError as exc:
        if exc.code not in {400, 403, 404}:
            raise ValueError('Anonymous artifact denial could not be established') from None
    print(json.dumps({'event': 'MKH_BENCHMARK_ARCHIVE', 'bucket': BUCKET,
                      'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                      'anonymous_public_read': 'denied'}), flush=True)


def export_aggregates(directory, card):
    # No answer excerpts, source passages, questions, user identifiers or claim
    # labels leave private artifacts. The exported inputs are computed, not rated.
    from .radar import VERSION, inputs
    measured = inputs(card, directory)
    exported = {k: v for k, v in card.items() if k not in {'findings', 'coverage_adjustments'}}
    findings = Counter((f['case_id'], f['kind']) for f in card.get('findings', []))
    exported['finding_counts'] = [{'case_id': case, 'kind': kind, 'count': count}
        for (case, kind), count in sorted(findings.items(), key=lambda row: (-row[1], row[0]))]
    exported['private_full_scorecard_sha256'] = digest(card)
    exported['aggregate_export_method'] = 'service-computed-v1; original attempts and judgments retained privately'
    result = {'scorecard': exported, 'radar_inputs': {'formula_version': VERSION,
        'scorecard_sha256': digest(exported), 'input_metrics': measured}}
    write_json(Path(directory) / 'exports/aggregate.json', result)
    encoded = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
    parts = [encoded[i:i + 3000] for i in range(0, len(encoded), 3000)]
    for index, part in enumerate(parts):
        print(json.dumps({'event': 'MKH_BENCHMARK_AGGREGATE', 'split': card['split'],
            'index': index, 'parts': len(parts), 'sha256': hashlib.sha256(encoded.encode()).hexdigest(),
            'data': part}), flush=True)


def run_from_environment():
    try:
        if not authorized(os.environ):
            return
        verify_freeze()
        settings = config(); label = os.environ['MKH_EVALUATION_RUN']; commit = os.environ['RENDER_GIT_COMMIT']
        from supabase import create_client
        storage = private_storage(create_client(settings['SUPABASE_URL'], settings['SUPABASE_SECRET_KEY']))
        prefix = f'{commit}/{label}'
        if any(x.get('name') == 'complete.zip' for x in storage.list(prefix)):
            print(json.dumps({'event': 'MKH_BENCHMARK_ALREADY_COMPLETE', 'commit': commit, 'label': label}), flush=True)
            return
        directory = Path('/tmp/mkh-evaluation') / commit / label
        directory.mkdir(parents=True, exist_ok=True); directory.chmod(0o700)
        # Render's disk is ephemeral. Resume private checkpoints rather than
        # silently buying a second run after a restart of the same milestone.
        existing = {x.get('name') for x in storage.list(prefix)}
        progress = sorted((name[:-4] for name in existing
            if re.fullmatch(r'judged-\d{6}\.zip', name)), reverse=True)
        for phase in progress + ['heldout-scored', 'rolling-scored', 'frozen-scored', 'captured', 'rolling-captured', 'frozen-captured']:
            if phase + '.zip' in existing:
                data = storage.download(f'{prefix}/{phase}.zip')
                with zipfile.ZipFile(io.BytesIO(data)) as zipped:
                    for member in zipped.infolist():
                        target = (directory / member.filename).resolve()
                        if not target.is_relative_to(directory.resolve()) or member.file_size > MAX_BYTES:
                            raise ValueError('Unsafe private checkpoint member')
                    if sum(m.file_size for m in zipped.infolist()) > 8 * MAX_BYTES:
                        raise ValueError('Private checkpoint expansion exceeds bound')
                    zipped.extractall(directory)
                break
        write_json(directory / 'milestone.json', {'started_at': now(), 'hub_commit': commit,
            'benchmark_manifest': verify_freeze(), 'service_id': SERVICE, 'access': 'synthetic anonymous benchmark only'})
        secrets = [settings.get('SUPABASE_SECRET_KEY'), settings.get('OPENAI_API_KEY')]
        from .corpus import capture
        from .judge import judge_run
        from .scorecard import summarize
        if not (directory / 'oracle.json').exists():
            capture(None, directory / 'oracle.json')
        oracle = json.loads((directory / 'oracle.json').read_text())
        # Complete latency capture before judge calls. Acceptance is a named,
        # explicitly enabled milestone; held-out answers never inform Hub input.
        splits = ['frozen', 'rolling', 'heldout']
        for split in splits:
            run(SimpleNamespace(output=str(directory / split), base=BASE, hub_commit=commit,
                split=split, acceptance=split == 'heldout', ids=None, require_commit=True,
                repetitions=3 if split == 'frozen' else 1,
                repeat_ids='JOIN01,JOIN02,JOIN03,FUND04' if split == 'frozen' else None))
            if split != 'heldout':
                checkpoint(storage, directory, prefix, split + '-captured', secrets)
        checkpoint(storage, directory, prefix, 'captured', secrets)
        public = provenance(directory / 'public-provenance')
        for split in splits:
            out = directory / split
            last_saved_count = sum(1 for path in directory.glob('*/judgments/*.json'))
            def persist_progress(_value):
                nonlocal last_saved_count
                count = sum(1 for path in directory.glob('*/judgments/*.json'))
                if count >= last_saved_count + 5:
                    checkpoint(storage, directory, prefix, f'judged-{count:06d}', secrets)
                    last_saved_count = count
            print(json.dumps({'event':'MKH_BENCHMARK_PHASE', 'split':split, 'phase':'judging'}),flush=True)
            judge_run(out, split, settings['OPENAI_API_KEY'], workers=2,
                acceptance=split == 'heldout', public_provenance=str(public), on_progress=persist_progress)
            count = sum(1 for path in directory.glob('*/judgments/*.json'))
            checkpoint(storage, directory, prefix, f'judged-{count:06d}', secrets)
            print(json.dumps({'event':'MKH_BENCHMARK_PHASE', 'split':split, 'phase':'scoring'}),flush=True)
            card = summarize(out, split, oracle, acceptance=split == 'heldout', label='Current candidate')
            export_aggregates(out, card)
            checkpoint(storage, directory, prefix, split + '-scored', secrets)
        checkpoint(storage, directory, prefix, 'complete', secrets)
        print(json.dumps({'event': 'MKH_BENCHMARK_COMPLETE', 'commit': commit, 'label': label}), flush=True)
    except Exception as exc:
        # Provider bodies and credentials must never reach application logs.
        print(json.dumps({'event': 'MKH_BENCHMARK_FAILED', 'error_type': type(exc).__name__}), flush=True)


async def launch():
    import asyncio
    await asyncio.sleep(10)  # Let the existing service bind and publish snapshots.
    await asyncio.to_thread(run_from_environment)
