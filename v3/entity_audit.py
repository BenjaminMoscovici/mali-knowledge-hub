"""Read and append reviewed entity decisions in the V2 versioned registry."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from normalization import EntityDecision

REGISTRY = Path(__file__).with_name("entity_decisions.json")


def load(path=REGISTRY):
    payload = json.loads(Path(path).read_text())
    decisions = [EntityDecision(**{k: v for k, v in item.items()
                                   if k in EntityDecision.__dataclass_fields__})
                 for item in payload["decisions"]]
    return payload, decisions


def append_reviewed(source, raw, canonical, *, supersedes=None,
                    reviewer, rationale, path=REGISTRY):
    if not source or not raw or not reviewer or not rationale:
        raise ValueError("Source, original value, reviewer and rationale are required")
    payload, decisions = load(path)
    if supersedes and supersedes not in {d.decision_id for d in decisions}:
        raise ValueError("Cannot supersede an unknown decision")
    if any(d.supersedes == supersedes for d in decisions) and supersedes:
        raise ValueError("Decision has already been superseded")
    if supersedes:
        prior = next(d for d in decisions if d.decision_id == supersedes)
        if (prior.source, prior.raw) != (source, raw):
            raise ValueError("Supersession must address the same source value")
    active = [d for d in decisions if (d.source, d.raw) == (source, raw)
              and not any(later.supersedes == d.decision_id for later in decisions)]
    if active and (not supersedes or active[0].decision_id != supersedes or len(active) != 1):
        raise ValueError("An active decision must be superseded explicitly")
    decision = EntityDecision(source, raw, canonical, "reviewed_manual", 1.0,
                              "resolved" if canonical else "uncertain",
                              str(uuid4()), supersedes, reviewer, rationale,
                              datetime.now(timezone.utc).isoformat())
    payload["decisions"].append(asdict(decision))
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--canonical", default=None,
                        help="Omit to mark the source value uncertain")
    parser.add_argument("--supersedes")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--rationale", required=True)
    args = parser.parse_args()
    print(append_reviewed(args.source, args.raw, args.canonical,
                          supersedes=args.supersedes, reviewer=args.reviewer,
                          rationale=args.rationale).decision_id)


if __name__ == "__main__":
    main()
