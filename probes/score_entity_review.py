"""Score the hand-labelled, conservative entity-resolution review sample."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "v2"))
from normalization import OrganizationResolver  # noqa: E402

sample = json.loads((ROOT / "v2/entity_review_sample.json").read_text())
resolver = OrganizationResolver(sample["canonical_names"])
results = []
for case in sample["cases"]:
    got = resolver.resolve(case["raw"], case["source"])
    results.append({"raw": case["raw"], "expected": case["expected"],
                    "predicted": got["canonical"], "status": got["status"],
                    "method": got["method"], "confidence": got["confidence"],
                    "correct": got["canonical"] == case["expected"]})
summary = {"cases": len(results), "correct": sum(r["correct"] for r in results),
           "false_merges": sum(r["expected"] is None and r["predicted"] is not None
                               for r in results),
           "missed_confirmed": sum(r["expected"] is not None and r["predicted"] is None
                                  for r in results),
           "results": results}
print(json.dumps(summary, ensure_ascii=False, indent=2))
