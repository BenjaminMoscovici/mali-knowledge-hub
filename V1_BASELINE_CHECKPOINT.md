# Mali Knowledge Hub V1 baseline checkpoint

Date: 2026-09-28. Source of truth: the uploaded v0.3 notebook and Python export.
The four governing documents were read before work began. No database mutation,
public deployment, or code change to the v0.3 baseline has occurred.

## Reproduction

- Extracted the notebook's embedded `app.py` and `knowledge_hub_runtime_v0_3.py`
  without modification and recorded SHA-256 hashes in `baseline_manifest.json`.
- Created a Python 3.12 virtual environment with system packages and installed
  OpenAI 3.19.2, Supabase 2.31.0, Streamlit 1.64.0, requests 2.34.2 and socksio.
  This is a local compatibility baseline, not a final dependency lock.
- The unchanged Streamlit app completed an AppTest startup with no exception.
- The deployed operational runtime in Supabase Storage is byte-identical to the
  runtime embedded in the uploaded notebook.

## Read-only backend baseline

- Five active documents and 1,239 chunks are present.
- FONGIM mirror row counts: projects 703; organizations 103; project organizations
  703; locations 2,767; sectors 1,369; partners 1,483; funding 328; sync runs 4.
- The `match_chunks` RPC is exposed. For frozen case D01, `text-embedding-3-small`
  consumed 18 input tokens and took about 10 seconds; the RPC returned 12 SNEDD
  chunks and took about 7 seconds. This is one observation, not a latency distribution.
- No answer synthesis or full-query cost measurement has completed.

## Benchmark

`benchmark_v1_frozen.json` was fixed before optimization: 24 questions, 18
development and six held out. SHA-256:
`96f4b9f32651d377f2388d14e0f9cd8018996c0d29ceaf5c1dcfb60a23a9f439`.
The held-out cases have not been executed or used for tuning.

## Data-transfer gate

The unchanged app would transmit retrieved Supabase corpus passages to OpenAI
for answer synthesis. Automatic approval review rejected that action twice:
public document provenance did not establish that every stored chunk and
structured field is non-sensitive or that this disclosure was explicitly
authorized. The five active records are four government documents with official
public PDF URLs and one publicly listed OCHA plan; see `public_source_audit.json`.
That classification is not byte-level verification of the stored corpus.

The next live baseline question is D01. It should run only after explicit
authorization for this transmission, or after a materially safer public-only
source route is established. The current v0.3 code has not been modified to
work around the rejection.
