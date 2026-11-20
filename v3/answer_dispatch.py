"""Run a resolved assignment through the same evidence paths for chat or a brief."""

import asyncio
import logging

from query_router import classify


LOG = logging.getLogger(__name__)


def conversational_route(question, mode):
    route = classify(question, mode)
    if route["path"] in {"country_fact", "simple_geography"}:
        from registry_research import named_registry_sources
        if named_registry_sources(question):
            return {"path": "deep_research" if mode == "deep" else "complex_research"}
    return route


def _lookup_assignment(question, path, language, presentation):
    from registry_observations import answer as registry_answer
    from registry_research import answer as registry_evidence_answer

    try:
        answer = registry_answer(question, language)
        if answer is not None:
            return answer, "registry_observation"
        answer = registry_evidence_answer(question, language)
        if answer is not None:
            return answer, "registry_evidence"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        LOG.warning("MKH_REGISTRY_LOOKUP_FAILURE %s", type(exc).__name__)

    if path == "country_fact":
        from country_foundation import country_foundation
        result = country_foundation().answer(question, language)
        if presentation == "brief" and result:
            from conversation_transform import compact_comparison
            result = compact_comparison(result)
        return result, path
    if path == "simple_geography":
        from geographic_model import geographic_model
        return geographic_model().answer(question, language), path
    return None, path


def _research_assignment(question, path, mode, language, presentation):
    from analysis_core import generate_grounded_answer, is_source_inventory_question, source_inventory_answer
    if is_source_inventory_question(question):
        return {"answer": source_inventory_answer(language), "evidence": [], "family_counts": {}}, path
    options = {"depth": mode, "response_language": language}
    if presentation:
        options["presentation"] = presentation
    return generate_grounded_answer(question, **options), path


async def answer_assignment(question, path, mode, language, *, research_limit,
                            presentation=None, allow_research=True):
    result, answer_path = await asyncio.to_thread(_lookup_assignment, question, path, language, presentation)
    if result is not None or not allow_research:
        return result, answer_path
    async with research_limit:
        return await asyncio.to_thread(_research_assignment, question, path, mode, language, presentation)
