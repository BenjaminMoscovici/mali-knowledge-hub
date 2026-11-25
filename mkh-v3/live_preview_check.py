"""Run an explicitly enabled, bounded research check inside the preview service."""

import logging
import os
import tempfile
import time
from pathlib import Path

from companion import CompanionError
from knowledge import json_text

LOG = logging.getLogger("uvicorn.error")
BRIEF = (
    "En français, prépare un court tableau d'aide à la décision pour les zones que le classeur "
    "Cadre Harmonisé rattache au libellé historique « Mopti ». Pour septembre–décembre 2025 "
    "et juin–août 2026, calcule la somme des personnes estimées en phase 3 ou plus et indique "
    "le nombre de zones. Vérifie auprès du bulletin CILSS si la seconde période est une "
    "observation ou une projection. Cite les sources et précise la limite géographique."
)
FOLLOW_UP = (
    "Garde le même périmètre et la même langue. Retire la période de 2025 et ajoute, séparément, "
    "les observations nationales de rendement des céréales pour 2023 et 2024, avec les unités et "
    "une phrase sur ce que ces observations nationales permettent de conclure."
)


def requested():
    try:
        deadline = int(os.getenv("MKH_PREVIEW_CHECK_UNTIL", "0"))
    except ValueError:
        return False
    if not 0 < deadline - time.time() <= 900:
        return False
    marker = Path(tempfile.gettempdir()) / f"mkh-preview-check-{deadline}"
    try:
        marker.touch(exist_ok=False)
    except FileExistsError:
        return False
    return True


def report(label, result):
    LOG.info("MKH live check %s %s", label, json_text(result))


async def assignment(companion, label, prompt, mode, history=(), evidence=()):
    try:
        async for event in companion.research(prompt, mode, history, evidence):
            if event["type"] == "answer":
                report(label, {
                    "usage": event["usage"], "partial": event["partial"],
                    "tool_failures": event["tool_failures"],
                    "citations": [
                        {field: item[field] for field in ("id", "source_id", "origin", "kind", "locator")
                         if field in item}
                        for item in event["evidence"]
                    ],
                    "answer": event["text"].replace(companion.api_key, "[redacted]")[:3800],
                })
                return event
    except CompanionError as error:
        report(label, {"error": str(error)})
    return None


async def run(companion):
    report("started", {"revision": os.getenv("RENDER_GIT_COMMIT", "local")})
    try:
        result = await assignment(companion, "mopti-fast", BRIEF, "fast")
        if result is None:
            return
        messages = [
            {"role": "user", "content": BRIEF},
            {"role": "assistant", "content": result["text"]},
        ]
        await assignment(companion, "mopti-follow-up-deep", FOLLOW_UP, "deep", messages, result["evidence"])
    except Exception as error:
        report("failed", {"error_type": type(error).__name__})
    finally:
        report("finished", {})
