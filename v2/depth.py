"""Internal V1 cost/quality configurations; all share citation safeguards."""

MODES = {
    "quick": {"document_count": 5, "max_output_tokens": 1000},
    "balanced": {"document_count": 8, "max_output_tokens": 1800},
    "deep": {"document_count": 12, "max_output_tokens": 2500},
}


def get_mode(name):
    if name not in MODES:
        raise ValueError(f"Unknown depth mode: {name}")
    return MODES[name]
