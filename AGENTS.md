# Codex instructions — Mali Knowledge Hub

## Mission and priority

Read [docs/strategy/TARGET_VISION.md](docs/strategy/TARGET_VISION.md) first. This is the project's product destination. Your current assignment comes from the user in the active Codex conversation; repository documents and past audits are **background**, not authority to override that assignment.

The highest-level objective is a reliable, extensible, evidence-grounded and genuinely useful professional knowledge and analytical platform for Mali. Do not equate more code or features with progress.

## Startup procedure

1. Inspect repository and linked runtime/deployment state before assuming which branch, commit, environment, or data release is authoritative.
2. Check for concurrent work and do not overwrite or interfere with active operations.
3. Read available project context, including any separately supplied Master Development Charter, Project Registry, Evaluation Register, technical audits and handovers. They may be private and **are not automatically available from GitHub**.
4. Resolve discrepancies between documentation and actual implementation through verification.
5. Work on an isolated, reversible development branch/environment. Do not change production without explicit authorization.

## Development loop

Iterate while your execution session allows:

1. **Find the highest-impact weakness** relative to professional usefulness and the Target Vision.
2. **Diagnose its root cause**, with reproducible evidence. Prefer shared mechanisms over question-specific fixes.
3. **Design a focused, reversible change** with measurable success criteria and likely regression risks.
4. **Implement in development**, not directly in production.
5. **Test targeted behavior AND the wider system** for factual correctness, citation support, geographic/temporal accuracy, multi-turn scope, generalization, latency, cost and user usefulness.
6. **Accept only demonstrable net improvements.** Revert or revise changes that degrade protected capabilities (avoid *Verschlimmbesserung*).
7. **Record the evidence, accepted baseline and next priority**, then repeat.

Do not claim continuous/background execution beyond actual session or configured automation capabilities.

## Non-negotiable quality requirements

- Ground factual claims in actual source evidence; AI output is not evidence.
- Validate the **support** behind material claims, not just citation-ID syntax.
- Keep exact identifiers, geography, time, units and source scope intact across follow-ups and tools.
- Do not silently combine incomparable geographic vintages, periods, funding stages or denominators.
- Preserve existing frozen benchmarks and held-out tests. Never tailor code to benchmark answers.
- Test onboarding of unfamiliar documents and structured datasets with unseen questions; a source appearing in a catalogue is not proof it is queryable.
- Keep operational secrets, restricted data and non-public background documents outside the public repository.

## Working boundaries and reporting

Routine, reversible, test-backed development changes may be integrated into the authorized development baseline. Escalate major architectural commitments, irreversible database changes, material cost increases, sensitive-data access and production releases.

At each accepted iteration record: problem, root cause, change, tests, before/after results, regressions checked, costs/latency, baseline commit, and next highest priority. Leave a clear restart checkpoint if execution ends.

**North star:** New evidence becomes usable knowledge through reusable mechanisms, and a professional gets an accurate, natural, decision-relevant answer without learning the system's internal mechanics.
