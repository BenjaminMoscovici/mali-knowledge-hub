"""Summarize reviewed professional tasks from one JSON object per attempt or billable turn."""

import argparse
from collections import defaultdict
from decimal import Decimal
import json
from pathlib import Path


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["variant"]].append(row)
    for variant, attempts in sorted(groups.items()):
        tasks = {row["task"] for row in attempts}
        outcomes = {}
        known_cost = Decimal(0)
        unpriced = 0
        for row in attempts:
            if row["estimated_usd"] is None:
                unpriced += 1
            else:
                cost = Decimal(str(row["estimated_usd"]))
                if not cost.is_finite() or cost < 0:
                    raise ValueError("Estimated cost must be finite and nonnegative.")
                known_cost += cost
            if row.get("accepted") is not None:
                if type(row["accepted"]) is not bool or row["task"] in outcomes:
                    raise ValueError("Record one final pass/fail review per task and variant.")
                outcomes[row["task"]] = row["accepted"]
        successes = sum(outcomes.values())
        pending = len(tasks - outcomes.keys())
        yield {"variant": variant, "tasks": len(tasks), "accepted": successes,
               "attempts_or_turns": len(attempts), "unreviewed_tasks": pending,
               "unpriced_attempts": unpriced, "known_estimated_usd": float(known_cost),
               "estimated_usd_per_accepted_task": float(known_cost / successes)
                    if successes and not pending and not unpriced else None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("attempts", type=Path, help="JSON Lines file with task, variant, estimated_usd and optional final accepted flag")
    args = parser.parse_args()
    with args.attempts.open() as stream:
        print(json.dumps(list(summarize(json.loads(line) for line in stream if line.strip())), indent=2))
