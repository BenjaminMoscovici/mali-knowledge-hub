
import os
import re
import json
import unicodedata
import time
import traceback
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import streamlit as st

from supabase import create_client
from openai import OpenAI
from metering import MeteredOpenAI, submit, PHASE
from routing import explicit_source_plan
from citations import verify as verify_citations
from depth import get_mode
from document_targets import named_targets, explicit_title_targets
from document_families import document_family
from language import answer_language
from hapi_cardinality import intersectoral_locality_note
from normalization import GeographyRegistry, OrganizationResolver, filter_hapi_rows
from entity_audit import load as load_entity_decisions
from joins import enrich as enrich_join_evidence, build_join_context, prompt_context
from user_research import (ResearchStore, ResearchStoreError,
                           evidence_references, hydrate_saved_evidence)


# ============================================================
# CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Mali Knowledge Hub",
    page_icon="🇲🇱",
    layout="wide"
)


def get_secret(name):
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return os.environ.get(name, "")


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_SECRET_KEY = get_secret("SUPABASE_SECRET_KEY")
SUPABASE_PUBLISHABLE_KEY = get_secret("SUPABASE_PUBLISHABLE_KEY")
OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
HDX_HAPI_APP_IDENTIFIER = get_secret(
    "HDX_HAPI_APP_IDENTIFIER"
)

if not all((SUPABASE_URL, SUPABASE_SECRET_KEY, OPENAI_API_KEY,
            HDX_HAPI_APP_IDENTIFIER)):
    st.title("Mali Knowledge Hub")
    st.info("The service is awaiting server-side configuration.")
    st.stop()


supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

openai_client = MeteredOpenAI(OpenAI(api_key=OPENAI_API_KEY))


# ============================================================
# VERSIONED LOCAL RUNTIME
# ============================================================

import knowledge_hub_runtime

knowledge_hub_runtime.configure_runtime(
    supabase,
    openai_client,
    HDX_HAPI_APP_IDENTIFIER
)


# ============================================================
# OPERATIONAL SOURCE FUNCTIONS
# ============================================================

search_knowledge_base = (
    knowledge_hub_runtime.search_knowledge_base
)

research_humanitarian_needs = (
    knowledge_hub_runtime.research_humanitarian_needs
)

run_fongim_sync_extract = (
    knowledge_hub_runtime.run_fongim_sync_extract
)


# ============================================================
# SOURCE REGISTRY
# ============================================================

SOURCE_REGISTRY = {
    "Government Framework Documents": [
        "Vision Mali 2063 — Mali Kura Ɲɛtaasira ka bɛn san 2063 ma",
        "Stratégie Nationale pour l’Émergence et le Développement Durable (SNEDD 2024–2033)",
        "Projets Structurants Prioritaires pour la mise en œuvre de Mali Kura 2063 et de la SNEDD 2024–2033",
        "Phasage des Projets Structurants Prioritaires"
    ],
    "Humanitarian Needs Assessment": [
        "Mali — Besoins humanitaires et Plan de Réponse 2026 (OCHA / Équipe Humanitaire Pays)"
    ],
    "OCHA Database": [
        "Live structured humanitarian-needs data queried through HDX HAPI"
    ],
    "International NGO Activities": [
        "Structured FONGIM project, location, sector and organization data from the synchronized Knowledge Hub operational mirror"
    ]
}


def is_source_inventory_question(question):
    """
    Detect questions about the Knowledge Hub's own source inventory.

    This must be broader than exact phrase matching because users may ask:
    - What are your sources?
    - What data do you use?
    - Which databases can you access?
    - What's in the Knowledge Hub?
    - Where does your information come from?
    """

    q = normalize_text(question).strip()

    if not q:
        return False

    exact_or_near_exact = [
        "what are your sources",
        "what are the sources",
        "what sources do you use",
        "which sources do you use",
        "what sources do you have",
        "which sources do you have",
        "what sources do you have access to",
        "which sources do you have access to",
        "what data do you use",
        "which data do you use",
        "what data do you have",
        "which data do you have",
        "what data can you access",
        "which data can you access",
        "what databases do you use",
        "which databases do you use",
        "what databases can you access",
        "which databases can you access",
        "what documents do you have",
        "which documents do you have",
        "what documents can you access",
        "which documents can you access",
        "what evidence do you use",
        "which evidence do you use",
        "where does your information come from",
        "where do your data come from",
        "where does your data come from",
        "what is in the knowledge hub",
        "whats in the knowledge hub",
        "what does the knowledge hub contain",
        "quelles sont tes sources",
        "quelles sont vos sources",
        "quelles sources utilises tu",
        "quelles sources utilisez vous",
        "quelles donnees utilises tu",
        "quelles donnees utilisez vous",
        "a quelles sources as tu acces",
        "a quelles sources avez vous acces",
        "welche quellen hast du",
        "welche quellen nutzt du",
        "auf welche quellen hast du zugriff",
        "welche daten nutzt du",
        "welche daten hast du",
        "auf welche daten hast du zugriff",
        "welche dokumente hast du",
        "auf welche dokumente hast du zugriff"
    ]

    if any(
        phrase in q
        for phrase in exact_or_near_exact
    ):
        return True

    # Robust semantic-style rule for short platform-inventory questions.
    source_terms = [
        "source",
        "sources",
        "data source",
        "data sources",
        "database",
        "databases",
        "document",
        "documents",
        "evidence",
        "quellen",
        "quelle",
        "daten",
        "dokumente",
        "sources",
        "donnees",
        "documents"
    ]

    inventory_terms = [
        "your",
        "you use",
        "you have",
        "you access",
        "available",
        "access to",
        "knowledge hub",
        "tes ",
        "vos ",
        "utilises",
        "utilisez",
        "acces",
        "hast du",
        "nutzt du",
        "zugriff",
        "verfugbar"
    ]

    has_source_term = any(
        term in q
        for term in source_terms
    )

    has_inventory_term = any(
        term in q
        for term in inventory_terms
    )

    # Keep this deliberately limited to short questions so that
    # substantive research questions mentioning "sources" are not hijacked.
    if (
        has_source_term
        and has_inventory_term
        and len(q.split()) <= 14
    ):
        return True

    return False


def source_inventory_answer():
    return """
I currently have access to **four source families**:

**1. Government Framework Documents**
- Vision Mali 2063 — *Mali Kura Ɲɛtaasira ka bɛn san 2063 ma*
- Stratégie Nationale pour l’Émergence et le Développement Durable (SNEDD 2024–2033)
- Projets Structurants Prioritaires for implementation of Mali Kura 2063 and SNEDD 2024–2033
- Phasage des Projets Structurants Prioritaires

**2. Humanitarian Needs Assessment**
- *Mali — Besoins humanitaires et Plan de Réponse 2026* (OCHA / Équipe Humanitaire Pays)

**3. OCHA Database**
- Live structured humanitarian-needs data queried through **HDX HAPI**. The Hub retrieves only records relevant to the question and preserves the source geography and categories.

**4. International NGO Activities**
- Structured **FONGIM** project data, including projects, locations, sectors and organizations. The app queries the synchronized Knowledge Hub operational mirror of the FONGIM source data.

The language model itself is **not** treated as a source. For analytical questions, the Hub selects the relevant source families and retrieves fresh evidence for that question.
""".strip()


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(value):
    value = str(value or "")

    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = "".join(
        c
        for c in value
        if not unicodedata.combining(c)
    )

    return value.lower().strip()


# ============================================================
# SUPABASE PAGINATION
# ============================================================

def fetch_all_rows(
    table_name,
    columns="*",
    eq_filters=None,
    page_size=1000
):

    if eq_filters is None:
        eq_filters = {}

    rows = []
    start = 0

    while True:

        query = (
            supabase
            .table(table_name)
            .select(columns)
        )

        for key, value in eq_filters.items():

            query = query.eq(
                key,
                value
            )

        response = (
            query
            .range(
                start,
                start + page_size - 1
            )
            .execute()
        )

        batch = response.data or []

        rows.extend(batch)

        if len(batch) < page_size:
            break

        start += page_size

    return rows


# ============================================================
# GEOGRAPHY RESOLVER
# ============================================================

@st.cache_data(ttl=3600)
def get_fongim_geographies():

    rows = fetch_all_rows(
        "fongim_project_locations",
        columns="region,cercle,commune_raw",
        eq_filters={
            "is_present_in_source": True
        }
    )

    regions = sorted({
        row.get("region")
        for row in rows
        if row.get("region")
    })

    cercles = sorted({
        row.get("cercle")
        for row in rows
        if row.get("cercle")
    })

    return {
        "regions": regions,
        "cercles": cercles,
        "locations": rows
    }


def find_name_in_question(
    question,
    candidates
):

    q = normalize_text(question)

    matches = []

    for candidate in candidates:

        normalized_candidate = normalize_text(
            candidate
        )

        pattern = (
            r"(?<!\w)"
            + re.escape(normalized_candidate)
            + r"(?!\w)"
        )

        if re.search(
            pattern,
            q
        ):
            matches.append(candidate)

    matches = sorted(
        matches,
        key=lambda x: len(str(x)),
        reverse=True
    )

    return matches


def _resolve_geography_v1(question):

    geographies = get_fongim_geographies()

    region_matches = find_name_in_question(
        question,
        geographies["regions"]
    )

    cercle_matches = find_name_in_question(
        question,
        geographies["cercles"]
    )

    q = normalize_text(question)

    explicit_region = None
    explicit_cercle = None

    # Preserve every named region in a comparison. Picking the first match
    # silently suppresses the other region's structured data.
    if len(region_matches) > 1:
        return {
            "region": None,
            "regions": region_matches,
            "cercle": None,
            "assumption": "Multiple named regions; query each separately."
        }

    for region in region_matches:

        r = normalize_text(region)

        if (
            f"region de {r}" in q
            or f"region du {r}" in q
            or f"region d'{r}" in q
            or f"region {r}" in q
            or f"{r} region" in q
        ):
            explicit_region = region
            break

    for cercle in cercle_matches:

        c = normalize_text(cercle)

        if (
            f"cercle de {c}" in q
            or f"cercle du {c}" in q
            or f"cercle d'{c}" in q
            or f"cercle {c}" in q
            or f"{c} cercle" in q
        ):
            explicit_cercle = cercle
            break

    if explicit_cercle:

        return {
            "region": explicit_region,
            "cercle": explicit_cercle,
            "assumption": None
        }

    if explicit_region:

        return {
            "region": explicit_region,
            "cercle": None,
            "assumption": None
        }

    if region_matches:

        region = region_matches[0]

        assumption = None

        if any(
            normalize_text(c)
            == normalize_text(region)
            for c in cercle_matches
        ):

            assumption = (
                f"Interpreted '{region}' as the region, "
                f"not the cercle."
            )

        return {
            "region": region,
            "cercle": None,
            "assumption": assumption
        }

    if cercle_matches:

        return {
            "region": None,
            "cercle": cercle_matches[0],
            "assumption": None
        }

    return {
        "region": None,
        "cercle": None,
        "assumption": None
    }


def resolve_geography(question):
    """Keep V1 query behavior, expose hierarchy and refuse uncertain circles."""
    result = _resolve_geography_v1(question)
    geographies = get_fongim_geographies()
    registry = GeographyRegistry(geographies["locations"])
    normalization = []
    for region in result.get("regions") or ([result["region"]] if result.get("region") else []):
        normalization.append(registry.resolve(region, level="region"))
    if result.get("cercle"):
        resolved = registry.resolve(result["cercle"], level="cercle",
                                    parent_region=result.get("region"))
        normalization.append(resolved)
        if resolved["status"] != "resolved":
            result["assumption"] = ("Cercle name is ambiguous across source "
                                    "locations; no cercle-specific query was made.")
            result["cercle"] = None
    result["normalization"] = normalization
    mentioned = find_name_in_question(question,
                                     geographies["regions"] + geographies["cercles"])
    result["homonyms"] = [registry.resolve(name) for name in sorted(set(mentioned))
                          if registry.resolve(name)["status"] == "ambiguous"]
    return result


# ============================================================
# SOURCE ROUTER
# ============================================================

HUMANITARIAN_KEYWORDS = [
    "humanitarian",
    "humanitaire",
    "besoin",
    "needs",
    "people in need",
    "personnes dans le besoin",
    "pin",
    "food security",
    "securite alimentaire",
    "nutrition",
    "wash",
    "eha",
    "health",
    "sante",
    "protection",
    "gbv",
    "violence basee sur le genre",
    "mine action",
    "deplacement",
    "deplace",
    "displacement"
]


FONGIM_KEYWORDS = [
    "project",
    "projet",
    "intervention",
    "programme",
    "organization",
    "organisation",
    "ong",
    "ngo",
    "actor",
    "acteur",
    "partner",
    "partenaire",
    "coverage",
    "couverture",
    "who works",
    "qui intervient",
    "sector",
    "secteur",
    "presence",
    "présence"
]


def contains_any_keyword(
    question,
    keywords
):

    q = normalize_text(question)

    return any(
        normalize_text(keyword) in q
        for keyword in keywords
    )


GOVERNMENT_KEYWORDS = [
    "government", "gouvernement", "etat", "state",
    "policy", "politique", "strategy", "strategie",
    "strategic", "priority", "priorite", "priorities",
    "vision", "snedd", "mali 2063", "mali kura",
    "projet structurant", "structural project",
    "local development", "developpement local",
    "decentralisation", "decentralization",
    "governance", "gouvernance"
]


CROSS_SOURCE_KEYWORDS = [
    "compare", "comparison", "comparer", "comparaison",
    "gap", "gaps", "lacune", "lacunes",
    "alignment", "alignement", "coordination",
    "nexus", "hdp", "humanitarian-development-peace",
    "humanitarian development peace",
    "opportunity", "opportunities",
    "opportunite", "opportunites",
    "mismatch", "tension", "synergy", "synergies"
]


PLANNER_SOURCE_ENUM = [
    "GOVERNMENT_DOCS",
    "HNRP",
    "HAPI",
    "FONGIM"
]


def plan_sources_semantically(question, geography=None):
    """
    Small structured planner.

    Its job is ONLY to identify information needs and source families.
    It must not answer the question, infer facts, or reason about
    geographic relationships.
    """

    started = time.perf_counter()

    direct_plan = explicit_source_plan(question)
    if direct_plan is not None:
        return {
            "source_plan": direct_plan,
            "planner_output": {"method": "explicit_source_rules"},
            "seconds": round(time.perf_counter() - started, 3),
        }

    system_prompt = """
You are the source planner for the Mali Knowledge Hub.

Your ONLY task is to decide which connected source families must be
queried to answer the user's question.

CONNECTED SOURCE FAMILIES:

GOVERNMENT_DOCS
- Mali government strategy, policy, planning and structural priorities
- Vision Mali 2063
- SNEDD 2024-2033
- Projets Structurants Prioritaires
- Phasage des Projets Structurants Prioritaires

HNRP
- Mali humanitarian plans, public appeals and situation reports, including
  newly ingested documents
- humanitarian priorities, response objectives, modalities and results

HAPI
- current Knowledge Hub connector for structured humanitarian-needs data
- use for quantitative / structured humanitarian needs

FONGIM
- structured operational project data
- organizations / NGOs / actors
- projects and interventions
- sectors
- project locations
- who is working where
- existing activities / operational presence

RULES:
1. Select every source family materially needed to answer the question.
2. Do NOT select a source merely because it might be interesting.
3. A question can require multiple source families.
4. "Who is working", "who is active", actors, NGOs, organizations,
   interventions, projects, activities, operational presence or coverage
   require FONGIM.
5. Humanitarian needs may require HNRP and/or HAPI:
   - HNRP for narrative priorities and response planning.
   - HAPI for structured humanitarian-needs figures.
6. Government priorities, policies, strategies, structural causes or
   planned structural responses require GOVERNMENT_DOCS.
7. Do not claim that a source contains a particular fact.
8. Do not reason about parent/child geography. Geography resolution is
   handled separately by deterministic code.
9. Do not answer the user's substantive question.
10. Return JSON only, matching the requested schema.
"""

    schema = {
        "type": "object",
        "properties": {
            "intents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "source_families": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": PLANNER_SOURCE_ENUM
                            }
                        }
                    },
                    "required": [
                        "topic",
                        "source_families"
                    ],
                    "additionalProperties": False
                }
            },
            "geo_entities": {
                "type": "array",
                "items": {"type": "string"}
            },
            "is_meta_question": {
                "type": "boolean"
            }
        },
        "required": [
            "intents",
            "geo_entities",
            "is_meta_question"
        ],
        "additionalProperties": False
    }

    response = openai_client.responses.create(
        model="gpt-5.6-luna",
        reasoning={"effort": "none"},
        max_output_tokens=500,
        input=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": question
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "mali_source_plan",
                "schema": schema,
                "strict": True
            }
        }
    )

    raw = response.output_text
    plan = json.loads(raw)

    selected = set()

    for intent in plan.get("intents", []):
        for source in intent.get("source_families", []):
            if source in PLANNER_SOURCE_ENUM:
                selected.add(source)

    source_plan = {
        "government_docs": "GOVERNMENT_DOCS" in selected,
        "hnrp_docs": "HNRP" in selected,
        "hapi": "HAPI" in selected,
        "fongim": "FONGIM" in selected
    }

    # Safe fallback: never allow a malformed/empty substantive plan
    # to silently suppress all evidence retrieval.
    if (
        not plan.get("is_meta_question", False)
        and not any(source_plan.values())
    ):
        source_plan = {
            "government_docs": True,
            "hnrp_docs": True,
            "hapi": False,
            "fongim": False
        }

    return {
        "source_plan": source_plan,
        "planner_output": plan,
        "seconds": round(
            time.perf_counter() - started,
            3
        )
    }




# ============================================================
# DOCUMENT FAMILY CLASSIFICATION
# ============================================================

def classify_document_family(item):
    return document_family(item)


# ============================================================
# DOCUMENT EVIDENCE
# ============================================================

@st.cache_data(ttl=60)
def get_document_groups():
    """
    Resolve document families dynamically from the document registry.

    Humanitarian plans, appeals and reports share a retrieval route.
    Government/development documents use the other route.
    """

    documents = (
        supabase
        .table("documents")
        .select("id,title,document_type,organization")
        .execute()
        .data
        or []
    )

    hnrp_document_ids = []
    government_document_ids = []

    for document in documents:

        document_id = document.get("id")

        if not document_id:
            continue

        if document_family(document) != "Government strategies":
            hnrp_document_ids.append(
                str(document_id)
            )
        else:
            government_document_ids.append(
                str(document_id)
            )

    return {
        "government":
            government_document_ids,

        "hnrp":
            hnrp_document_ids,

        "documents": documents
    }


def build_document_evidence(
    question,
    use_government=True,
    use_hnrp=True,
    government_count=8,
    hnrp_count=8
):

    function_started = time.perf_counter()

    document_groups = get_document_groups()

    government_document_ids = document_groups["government"]
    hnrp_document_ids = document_groups["hnrp"]
    targeted_documents = list(dict.fromkeys(
        named_targets(question, document_groups["documents"])
        + explicit_title_targets(question, document_groups["documents"])
    ))
    government_targets = [(doc_id, title) for doc_id, title in targeted_documents
                          if doc_id in government_document_ids]
    humanitarian_targets = [(doc_id, title) for doc_id, title in targeted_documents
                            if doc_id in hnrp_document_ids]

    trace = {
        "government_docs": {
            "requested": bool(use_government),
            "status": "NOT_REQUESTED",
            "seconds": 0.0,
            "records": 0
        },
        "hnrp_docs": {
            "requested": bool(use_hnrp),
            "status": "NOT_REQUESTED",
            "seconds": 0.0,
            "records": 0
        }
    }

    def retrieve_government():
        if not use_government or not government_document_ids:
            return [], 0.0

        started = time.perf_counter()

        government_query = f"""
{question}

Retrieve evidence specifically about Mali's national development
strategy, long-term policy priorities, government objectives,
Vision Mali 2063, SNEDD 2024-2033, structural projects and
development planning.

Focus on the government/development evidence most relevant to the
user's question.
"""

        if government_targets:
            per_document_count = max(3, (government_count + len(government_targets) - 1) // len(government_targets))
            with ThreadPoolExecutor(max_workers=len(government_targets)) as executor:
                futures = [submit(executor, search_knowledge_base,
                                  f"{question}\nFocus on: {title}",
                                  per_document_count, [document_id])
                           for document_id, title in government_targets]
                results = [chunk for future in futures for chunk in future.result()]
        else:
            results = search_knowledge_base(
                government_query,
                match_count=government_count,
                filter_document_ids=government_document_ids
            )

        return results, time.perf_counter() - started

    def retrieve_hnrp():
        if not use_hnrp or not hnrp_document_ids:
            return [], 0.0

        started = time.perf_counter()

        hnrp_query = f"""
{question}

Retrieve evidence specifically from Mali's humanitarian needs
and response planning documents, including humanitarian needs,
response priorities, humanitarian objectives and HNRP 2026.

Focus on the humanitarian planning evidence most relevant to the
user's question.
"""

        if humanitarian_targets:
            per_document_count = max(3, (hnrp_count + len(humanitarian_targets) - 1) // len(humanitarian_targets))
            with ThreadPoolExecutor(max_workers=len(humanitarian_targets)) as executor:
                futures = [submit(executor, search_knowledge_base,
                                  f"{question}\nFocus on: {title}",
                                  per_document_count, [document_id])
                           for document_id, title in humanitarian_targets]
                results = [chunk for future in futures for chunk in future.result()]
        else:
            results = search_knowledge_base(
                hnrp_query,
                match_count=hnrp_count,
                filter_document_ids=hnrp_document_ids
            )

        return results, time.perf_counter() - started

    if use_government and use_hnrp:
        with ThreadPoolExecutor(max_workers=2) as executor:
            government_future = submit(executor,
                retrieve_government
            )
            hnrp_future = submit(executor,
                retrieve_hnrp
            )
            government_results, government_seconds = (
                government_future.result()
            )
            hnrp_results, hnrp_seconds = (
                hnrp_future.result()
            )
    else:
        government_results, government_seconds = (
            retrieve_government()
        )
        hnrp_results, hnrp_seconds = (
            retrieve_hnrp()
        )

    if use_government:
        trace["government_docs"].update({
            "status": (
                "SUCCESS_WITH_RESULTS"
                if government_results
                else "SUCCESS_ZERO_RESULTS"
            ),
            "seconds": round(government_seconds, 3),
            "records": len(government_results)
        })

    if use_hnrp:
        trace["hnrp_docs"].update({
            "status": (
                "SUCCESS_WITH_RESULTS"
                if hnrp_results
                else "SUCCESS_ZERO_RESULTS"
            ),
            "seconds": round(hnrp_seconds, 3),
            "records": len(hnrp_results)
        })

    combined = government_results + hnrp_results

    seen = set()
    evidence = []

    for result in combined:
        dedupe_key = (
            result.get("document_id"),
            result.get("page_number"),
            result.get("section_title"),
            result.get("content")
        )

        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)

        evidence.append({
            "source_type": "knowledge_base_document",
            "source_family": classify_document_family(result),
            "document_id": result.get("document_id"),
            "chunk_id": result.get("id"),
            "document_title": result.get("document_title"),
            "document_type": result.get("document_type"),
            "organization": result.get("organization"),
            "version": result.get("version"),
            "publication_date": result.get("publication_date"),
            "valid_from": result.get("valid_from"),
            "valid_until": result.get("valid_until"),
            "geographic_scope": result.get("geographic_scope"),
            "page": result.get("page_number"),
            "section": result.get("section_title"),
            "similarity": result.get("similarity"),
            "content": result.get("content")
        })

    trace["total_seconds"] = round(
        time.perf_counter() - function_started,
        3
    )

    return {
        "evidence": evidence,
        "trace": trace
    }


# ============================================================
# HAPI REDUCER
# ============================================================

def reduce_hapi_humanitarian_evidence(
    evidence_items,
    max_sector_examples=8
):
    """
    Reduce HAPI humanitarian-needs records while preserving
    geography, denominator and analytical scope.

    Principles:
    1. Use aggregate population_category='total' whenever available.
    2. Never sum Admin2 observations into an Admin1 total.
    3. Prefer true Admin1 observations for region-level analysis.
    4. If only Admin2 observations exist, preserve complete
       intersectoral coverage and use sector figures only as
       locality-specific observations.
    5. Never present the largest Admin2 sector observation as a
       region-wide sector ranking.
    """

    if not evidence_items:
        return []

    # --------------------------------------------------------
    # 1. KEEP AGGREGATE POPULATION RECORDS
    # --------------------------------------------------------

    total_rows = [
        item
        for item in evidence_items
        if normalize_text(
            item.get("population_category")
        ) == "total"
    ]

    # Conservative fallback:
    # do not attempt analytical ranking from demographic slices.
    if not total_rows:
        fallback = []

        for item in evidence_items[:30]:
            fallback.append({
                **item,
                "passage": (
                    str(item.get("passage") or "")
                    + " NOTE: No population_category='total' "
                    "record was available in this result set. "
                    "This record is a population subgroup and "
                    "must not be interpreted as the total number "
                    "of people in need."
                )
            })

        return fallback


    # --------------------------------------------------------
    # 2. IDENTIFY GEOGRAPHIC STRUCTURE
    # --------------------------------------------------------

    admin1_rows = [
        item
        for item in total_rows
        if item.get("admin_level") == 1
    ]

    admin2_rows = [
        item
        for item in total_rows
        if item.get("admin_level") == 2
    ]


    # --------------------------------------------------------
    # 3. IF TRUE ADMIN1 DATA EXIST, USE THEM
    # --------------------------------------------------------

    if admin1_rows:

        intersectoral = [
            item
            for item in admin1_rows
            if normalize_text(
                item.get("sector_name")
            ) == "intersectoral"
        ]

        sector_rows = [
            item
            for item in admin1_rows
            if normalize_text(
                item.get("sector_name")
            ) != "intersectoral"
        ]

        # One aggregate observation per sector.
        # If duplicates exist, keep the largest documented value
        # but preserve the original geography and period.
        best_by_sector = {}

        for item in sector_rows:

            sector = (
                item.get("sector_name")
                or "Unspecified sector"
            )

            current = best_by_sector.get(
                sector
            )

            if (
                current is None
                or (
                    item.get("value") or 0
                ) > (
                    current.get("value") or 0
                )
            ):
                best_by_sector[
                    sector
                ] = item

        ranked_sector_rows = sorted(
            best_by_sector.values(),
            key=lambda x:
                x.get("value") or 0,
            reverse=True
        )

        selected = (
            intersectoral
            + ranked_sector_rows[
                :max_sector_examples
            ]
        )

        result = []

        for item in selected:

            result.append({
                **item,
                "passage": (
                    str(item.get("passage") or "")
                    + " This is an Admin1-level aggregate "
                    "observation for the stated geography and "
                    "reference period."
                )
            })

        return result


    # --------------------------------------------------------
    # 4. OTHERWISE PRESERVE ADMIN2 STRUCTURE
    # --------------------------------------------------------

    working_rows = (
        admin2_rows
        if admin2_rows
        else total_rows
    )

    intersectoral = [
        item
        for item in working_rows
        if normalize_text(
            item.get("sector_name")
        ) == "intersectoral"
    ]

    # Keep all intersectoral locality totals.
    intersectoral = sorted(
        intersectoral,
        key=lambda x: (
            x.get("admin1_name") or "",
            x.get("admin2_name") or ""
        )
    )

    intersectoral_with_scope = []

    for item in intersectoral:

        intersectoral_with_scope.append({
            **item,
            "passage": (
                str(item.get("passage") or "")
                + " This is an Admin2/locality observation. "
                "It must not be summed with other Admin2 "
                "observations to manufacture an Admin1 total."
            )
        })


    # --------------------------------------------------------
    # 5. SECTOR OBSERVATIONS
    # --------------------------------------------------------

    sector_rows = [
        item
        for item in working_rows
        if normalize_text(
            item.get("sector_name")
        ) != "intersectoral"
    ]

    # For each sector, retain the largest documented locality
    # observation purely as an illustrative severity signal.
    # This is NOT a regional sector total.
    best_by_sector = {}

    for item in sector_rows:

        sector = (
            item.get("sector_name")
            or "Unspecified sector"
        )

        current = best_by_sector.get(
            sector
        )

        if (
            current is None
            or (
                item.get("value") or 0
            ) > (
                current.get("value") or 0
            )
        ):
            best_by_sector[
                sector
            ] = item


    sector_examples = sorted(
        best_by_sector.values(),
        key=lambda x:
            x.get("value") or 0,
        reverse=True
    )[:max_sector_examples]


    sector_examples_with_scope = []

    for item in sector_examples:

        sector_examples_with_scope.append({
            **item,
            "passage": (
                str(item.get("passage") or "")
                + " This is the largest recorded Admin2 "
                "observation for this sector within the returned "
                "result set. It is NOT an Admin1 total and must "
                "not be interpreted as a region-wide sector "
                "caseload or as proof that this sector is the "
                "region's most severe need."
            )
        })


    # --------------------------------------------------------
    # 6. COMBINE
    # --------------------------------------------------------

    return (
        intersectoral_with_scope
        + sector_examples_with_scope
    )

@st.cache_data(ttl=900, show_spinner=False)
def build_hapi_evidence(
    geography
):

    raw = research_humanitarian_needs(
        admin1_name=(
            geography.get("region")
            if not geography.get("cercle")
            else None
        ),
        admin2_name=geography.get(
            "cercle"
        ),
        population_status="INN",
        latest_only=True,
        limit=10000
    )

    # HAPI has returned rows for a different Admin2 even when an Admin2
    # name was sent. Validate returned geography before any reduction.
    wanted_cercle = geography.get("cercle")
    wanted_region = geography.get("region")
    raw = filter_hapi_rows(raw, region=wanted_region, cercle=wanted_cercle)

    # A regional fallback is explicitly broader context, never a substitute
    # for a missing cercle observation.
    broader_context = False
    if wanted_cercle and not raw and wanted_region:
        raw = research_humanitarian_needs(
            admin1_name=wanted_region,
            population_status="INN", latest_only=True, limit=10000
        )
        raw = filter_hapi_rows(raw, region=wanted_region)
        broader_context = True

    reduced = (
        reduce_hapi_humanitarian_evidence(
            raw
        )
    )

    evidence = []

    for item in reduced:

        evidence.append({
            **item,

            "source_family":
                "OCHA humanitarian data",

            "content":
                ((f"Broader {wanted_region} region context only; no matching "
                  f"{wanted_cercle} cercle record was returned. "
                  if broader_context else "") + str(item.get("passage") or "")),

            "document_title":
                item.get(
                    "dataset_title"
                )
                or item.get(
                    "document_title"
                )
                or "HDX HAPI",

            "page":
                None,

            "section":
                item.get(
                    "sector_name"
                ),

            "organization":
                item.get(
                    "provider_name"
                )
                or "OCHA / HDX",

            "version":
                None
        })

    return {
        "raw_count": len(raw),
        "evidence": evidence
    }


# ============================================================
# FONGIM STRUCTURED RESEARCH
# ============================================================

def get_rows_for_project_ids(
    table_name,
    columns,
    project_ids,
    chunk_size=300
):

    if not project_ids:
        return []

    rows = []

    for start in range(
        0,
        len(project_ids),
        chunk_size
    ):

        chunk = project_ids[
            start:start + chunk_size
        ]

        response = (
            supabase
            .table(table_name)
            .select(columns)
            .in_(
                "fongim_project_id",
                chunk
            )
            .eq(
                "is_present_in_source",
                True
            )
            .execute()
        )

        rows.extend(
            response.data or []
        )

    return rows


@st.cache_data(ttl=900, show_spinner=False)
def research_fongim(
    geography
):

    location_filters = {
        "is_present_in_source": True
    }

    if geography.get("region"):
        location_filters["region"] = geography["region"]

    if geography.get("cercle"):
        location_filters["cercle"] = geography["cercle"]

    locations = fetch_all_rows(
        "fongim_project_locations",
        columns=(
            "fongim_project_id,"
            "region,"
            "cercle,"
            "commune_raw,"
            "last_synced_at"
        ),
        eq_filters=location_filters
    )

    project_ids = sorted({
        row.get("fongim_project_id")
        for row in locations
        if row.get("fongim_project_id") is not None
    })

    if not project_ids:
        return {
            "project_count": 0,
            "location_count": 0,
            "evidence": []
        }

    projects = get_rows_for_project_ids(
        "fongim_projects",
        (
            "fongim_project_id,"
            "project_name,"
            "start_date,"
            "end_date,"
            "status,"
            "project_type,"
            "beneficiaries,"
            "donor,"
            "funding_amount_raw,"
            "last_synced_at"
        ),
        project_ids
    )

    sectors = get_rows_for_project_ids(
        "fongim_project_sectors",
        (
            "fongim_project_id,"
            "sector,"
            "sector_other_raw"
        ),
        project_ids
    )

    project_orgs = get_rows_for_project_ids(
        "fongim_project_organizations",
        (
            "fongim_project_id,"
            "fongim_organization_id"
        ),
        project_ids
    )

    organization_ids = sorted({
        row.get("fongim_organization_id")
        for row in project_orgs
        if row.get("fongim_organization_id") is not None
    })

    organizations = []

    if organization_ids:
        response = (
            supabase
            .table("fongim_organizations")
            .select(
                "fongim_organization_id,"
                "organization_name"
            )
            .in_(
                "fongim_organization_id",
                organization_ids
            )
            .eq(
                "is_present_in_source",
                True
            )
            .execute()
        )

        organizations = response.data or []

    org_name_by_id = {
        row.get("fongim_organization_id"):
        row.get("organization_name")
        for row in organizations
    }


    # --------------------------------------------------------
    # PROJECT-LEVEL RELATIONAL MAPS
    # --------------------------------------------------------

    sectors_by_project = defaultdict(set)

    for row in sectors:
        project_id = row.get("fongim_project_id")
        sector = row.get("sector") or "Unspecified"

        if project_id is not None:
            sectors_by_project[project_id].add(sector)

    orgs_by_project = defaultdict(set)

    for row in project_orgs:
        project_id = row.get("fongim_project_id")
        org_id = row.get("fongim_organization_id")

        org_name = (
            org_name_by_id.get(org_id)
            or str(org_id)
        )

        if project_id is not None:
            orgs_by_project[project_id].add(org_name)


    # --------------------------------------------------------
    # SECTOR COUNTS
    # --------------------------------------------------------

    sector_projects = defaultdict(set)

    for project_id, project_sectors in sectors_by_project.items():
        for sector in project_sectors:
            sector_projects[sector].add(project_id)

    top_sectors = sorted(
        (
            (sector, len(ids))
            for sector, ids in sector_projects.items()
        ),
        key=lambda x: x[1],
        reverse=True
    )


    # --------------------------------------------------------
    # CERCLE COUNTS
    # --------------------------------------------------------

    circle_projects = defaultdict(set)

    for row in locations:
        cercle = row.get("cercle")

        if cercle:
            circle_projects[cercle].add(
                row.get("fongim_project_id")
            )

    top_cercles = sorted(
        (
            (cercle, len(ids))
            for cercle, ids in circle_projects.items()
        ),
        key=lambda x: x[1],
        reverse=True
    )


    # --------------------------------------------------------
    # ORGANIZATION COUNTS
    # --------------------------------------------------------

    org_projects = defaultdict(set)

    for project_id, project_org_names in orgs_by_project.items():
        for org_name in project_org_names:
            org_projects[org_name].add(project_id)

    top_orgs = sorted(
        (
            (org, len(ids))
            for org, ids in org_projects.items()
        ),
        key=lambda x: x[1],
        reverse=True
    )


    # --------------------------------------------------------
    # CROSS-DIMENSIONAL ORGANIZATION × SECTOR ANALYSIS
    # --------------------------------------------------------

    org_sector_projects = defaultdict(
        lambda: defaultdict(set)
    )

    sector_org_projects = defaultdict(
        lambda: defaultdict(set)
    )

    for project_id in project_ids:

        project_org_names = orgs_by_project.get(
            project_id,
            set()
        )

        project_sectors = sectors_by_project.get(
            project_id,
            set()
        )

        for org_name in project_org_names:
            for sector in project_sectors:

                org_sector_projects[
                    org_name
                ][
                    sector
                ].add(project_id)

                sector_org_projects[
                    sector
                ][
                    org_name
                ].add(project_id)


    org_sector_breadth = sorted(
        (
            (
                org_name,
                len(sector_map),
                sum(
                    len(ids)
                    for ids in sector_map.values()
                )
            )
            for org_name, sector_map
            in org_sector_projects.items()
        ),
        key=lambda x: (
            -x[1],
            -x[2],
            x[0]
        )
    )


    # --------------------------------------------------------
    # GEOGRAPHIC SCOPE
    # --------------------------------------------------------

    scope_parts = []

    if geography.get("region"):
        scope_parts.append(
            f"region={geography['region']}"
        )

    if geography.get("cercle"):
        scope_parts.append(
            f"cercle={geography['cercle']}"
        )

    geographic_scope = (
        ", ".join(scope_parts)
        if scope_parts
        else "Mali"
    )

    latest_sync = max(
        [
            str(row.get("last_synced_at"))
            for row in projects
            if row.get("last_synced_at")
        ],
        default=None
    )


    # --------------------------------------------------------
    # BUILD STRUCTURED EVIDENCE
    # --------------------------------------------------------

    evidence = []

    evidence.append({
        "source_type": "fongim_structured",
        "source_family": "FONGIM intervention data",
        "document_title": "FONGIM operational project data",
        "document_type": "structured_operational_data",
        "organization": "FONGIM",
        "version": None,
        "page": None,
        "section": geographic_scope,
        "content": (
            f"FONGIM records {len(project_ids)} unique projects "
            f"with at least one recorded location in "
            f"{geographic_scope}, represented by "
            f"{len(locations)} project-location records. "
            f"Latest synchronization timestamp among "
            f"these project records: {latest_sync}. "
            f"These counts describe recorded project presence; "
            f"they do not demonstrate funding adequacy, "
            f"population coverage, implementation quality "
            f"or impact."
        )
    })


    if top_sectors:

        sector_text = "; ".join(
            f"{sector}: {count} projects"
            for sector, count in top_sectors[:10]
        )

        evidence.append({
            "source_type": "fongim_structured",
            "source_family": "FONGIM intervention data",
            "document_title": "FONGIM operational project data",
            "document_type": "structured_operational_data",
            "organization": "FONGIM",
            "version": None,
            "page": None,
            "section": "Sector profile",
            "content": (
                f"Among FONGIM projects with at least one "
                f"recorded location in {geographic_scope}, "
                f"the number of unique projects associated "
                f"with each leading sector is: "
                f"{sector_text}. "
                f"A project may be associated with more than "
                f"one sector, so sector counts must not be summed "
                f"to derive a project total."
            )
        })


    if top_cercles:

        cercle_text = "; ".join(
            f"{cercle}: {count} projects"
            for cercle, count in top_cercles[:10]
        )

        evidence.append({
            "source_type": "fongim_structured",
            "source_family": "FONGIM intervention data",
            "document_title": "FONGIM operational project data",
            "document_type": "structured_operational_data",
            "organization": "FONGIM",
            "version": None,
            "page": None,
            "section": "Recorded geographic presence",
            "content": (
                f"Unique FONGIM projects with a recorded "
                f"location in each cercle within the selected "
                f"scope: {cercle_text}. "
                f"This is a count of recorded project presence, "
                f"not a measure of needs coverage or resources."
            )
        })


    if top_orgs:

        org_text = "; ".join(
            f"{org}: {count} projects"
            for org, count in top_orgs[:10]
        )

        evidence.append({
            "source_type": "fongim_structured",
            "source_family": "FONGIM intervention data",
            "document_title": "FONGIM operational project data",
            "document_type": "structured_operational_data",
            "organization": "FONGIM",
            "version": None,
            "page": None,
            "section": "Organizations",
            "content": (
                f"Primary organizations associated with "
                f"FONGIM projects in {geographic_scope}: "
                f"{org_text}. "
                f"Counts refer to projects linked to each "
                f"primary organization in the source."
            )
        })


    # --------------------------------------------------------
    # ORGANIZATION × SECTOR EVIDENCE
    # --------------------------------------------------------

    if org_sector_breadth:

        org_sector_lines = []

        for org_name, sector_count, _ in org_sector_breadth:

            sector_map = org_sector_projects[
                org_name
            ]

            sector_details = sorted(
                (
                    (
                        sector,
                        len(ids)
                    )
                    for sector, ids
                    in sector_map.items()
                ),
                key=lambda x: (
                    -x[1],
                    x[0]
                )
            )

            sector_text = ", ".join(
                f"{sector} ({count} projects)"
                for sector, count
                in sector_details
            )

            org_sector_lines.append(
                f"{org_name}: "
                f"{sector_count} distinct sectors — "
                f"{sector_text}"
            )

        evidence.append({
            "source_type": "fongim_structured",
            "source_family": "FONGIM intervention data",
            "document_title": "FONGIM operational project data",
            "document_type": "structured_operational_data",
            "organization": "FONGIM",
            "version": None,
            "page": None,
            "section": "Organization-sector relationships",
            "content": (
                f"Project-level organization-sector relationships "
                f"for FONGIM projects in {geographic_scope}. "
                f"Each organization below is linked to the listed "
                f"sector because at least one project associated "
                f"with that organization is also associated with "
                f"that sector. Counts in parentheses are unique "
                f"projects for that organization-sector combination. "
                f"Distinct-sector counts describe recorded thematic "
                f"breadth, not organizational effectiveness or "
                f"quality. "
                + "; ".join(org_sector_lines)
            )
        })


    # --------------------------------------------------------
    # SECTOR × ORGANIZATION EVIDENCE
    # --------------------------------------------------------

    if sector_org_projects:

        sector_org_lines = []

        for sector, org_map in sorted(
            sector_org_projects.items(),
            key=lambda item: (
                -len(sector_projects.get(
                    item[0],
                    set()
                )),
                item[0]
            )
        ):

            org_details = sorted(
                (
                    (
                        org_name,
                        len(ids)
                    )
                    for org_name, ids
                    in org_map.items()
                ),
                key=lambda x: (
                    -x[1],
                    x[0]
                )
            )

            org_text = ", ".join(
                f"{org_name} ({count} projects)"
                for org_name, count
                in org_details
            )

            sector_org_lines.append(
                f"{sector}: {org_text}"
            )

        evidence.append({
            "source_type": "fongim_structured",
            "source_family": "FONGIM intervention data",
            "document_title": "FONGIM operational project data",
            "document_type": "structured_operational_data",
            "organization": "FONGIM",
            "version": None,
            "page": None,
            "section": "Sector-organization relationships",
            "content": (
                f"Project-level sector-organization relationships "
                f"for FONGIM projects in {geographic_scope}. "
                f"Organizations are listed under a sector when "
                f"at least one project associated with that "
                f"organization is also associated with that sector. "
                f"Counts in parentheses are unique projects for "
                f"that sector-organization combination. "
                + "; ".join(sector_org_lines)
            )
        })


    project_examples = sorted(
        [
            p
            for p in projects
            if p.get("project_name")
        ],
        key=lambda x:
            str(x.get("project_name"))
    )[:8]

    if project_examples:

        examples_text = "; ".join(
            (
                f"{p.get('project_name')}"
                + (
                    f" [{p.get('status')}]"
                    if p.get("status")
                    else ""
                )
            )
            for p in project_examples
        )

        evidence.append({
            "source_type": "fongim_structured",
            "source_family": "FONGIM intervention data",
            "document_title": "FONGIM operational project data",
            "document_type": "structured_operational_data",
            "organization": "FONGIM",
            "version": None,
            "page": None,
            "section": "Illustrative project records",
            "content": (
                f"Illustrative project records from the "
                f"selected FONGIM result set: "
                f"{examples_text}. "
                f"These examples are illustrative and are "
                f"not a ranking of projects."
            )
        })

    # Exact project-ID joins in the operational mirror. These relationships
    # are recorded activity, not proof of target attainment or impact.
    locations_by_project = defaultdict(set)
    for row in locations:
        project_id = row.get("fongim_project_id")
        if project_id is not None:
            locations_by_project[project_id].add(
                (row.get("region") or "?", row.get("cercle") or "?",
                 row.get("commune_raw") or "")
            )
    selected = project_examples[:5]
    for project in selected:
        pid = project["fongim_project_id"]
        place = sorted(locations_by_project.get(pid, []))[:4]
        evidence.append({
            "source_type": "fongim_structured",
            "source_family": "FONGIM intervention data",
            "document_title": "FONGIM operational project data",
            "document_type": "structured_operational_data",
            "organization": "FONGIM",
            "version": None, "page": None,
            "section": "Project-ID relationship",
            "geographic_scope": geographic_scope,
            "content": (
                f"FONGIM project ID {pid}: {project['project_name']}. "
                f"Recorded organization names: {sorted(orgs_by_project.get(pid, []))}. "
                f"Recorded sectors: {sorted(sectors_by_project.get(pid, []))}. "
                f"Recorded locations (region, cercle, raw commune): {place}. "
                f"Status: {project.get('status')}; start/end dates: "
                f"{project.get('start_date')} / {project.get('end_date')}; "
                f"latest sync: {project.get('last_synced_at')}. "
                "This is recorded project presence, not verified coverage or impact."
            )
        })


    return {
        "project_count": len(project_ids),
        "location_count": len(locations),
        "evidence": evidence,
        "organization_names": sorted(set(org_name_by_id.values()) - {None, ""})
    }

# ============================================================
# UNIFIED EVIDENCE LEDGER
# ============================================================

def build_unified_evidence(
    document_evidence,
    hapi_evidence,
    fongim_evidence
):

    combined = (
        document_evidence
        + hapi_evidence
        + fongim_evidence
    )

    ledger = []

    for index, item in enumerate(
        combined,
        1
    ):

        ledger.append({
            **item,
            "evidence_id":
                f"E{index:02d}"
        })

    return ledger


# ============================================================
# EVIDENCE SERIALIZATION
# ============================================================

def evidence_to_prompt(
    ledger
):

    blocks = []

    for item in ledger:

        blocks.append(
            f"""
[{item['evidence_id']}]
SOURCE FAMILY: {item.get('source_family')}
SOURCE TYPE: {item.get('source_type')}
SOURCE: {item.get('document_title')}
ORGANIZATION: {item.get('organization')}
TYPE: {item.get('document_type')}
VERSION: {item.get('version')}
PUBLICATION DATE: {item.get('publication_date')}
VALIDITY: {item.get('valid_from')} to {item.get('valid_until')}
GEOGRAPHIC SCOPE: {item.get('geographic_scope')}
ADMIN1 / ADMIN2: {item.get('admin1_name')} / {item.get('admin2_name')}
PAGE: {item.get('page')}
SECTION: {item.get('section')}
EVIDENCE TYPE CUES (classification only): {item.get('evidence_types')}
NORMALIZED SECTOR TERMS (curated lexical mapping): {list(item.get('normalized_sectors', {}))}

EVIDENCE:
{item.get('content')}

---
"""
        )

    return "\n".join(
        blocks
    )


# ============================================================
# FOUR-SOURCE RESEARCH
# ============================================================

def run_four_source_research(question, document_count=8):

    total_started = time.perf_counter()

    planner_result = plan_sources_semantically(question)

    source_plan = planner_result["source_plan"]
    routing_seconds = planner_result["seconds"]
    needs_geo_inventory = (not any(source_plan.values()) and bool(re.search(
        r"\b(region|cercle|commune|administrative level|geograph)",
        normalize_text(question))))
    needs_entity_policy = bool(re.search(
        r"\b(?:organisations?|organizations?|entit(?:y|ies)|acronyms?|acronymes?|merge|fusion)\b",
        normalize_text(question), re.I)) and bool(re.search(
        r"\b(?:same|similar|meme|similaire|match|merge|fusion)\b",
        normalize_text(question), re.I))
    entity_method_question = needs_entity_policy and bool(re.search(
        r"\b(?:necessarily|how is a wrong merge|when can the hub merge|"
        r"may the hub merge)\b", normalize_text(question), re.I))
    count_method_question = (source_plan["fongim"] and bool(re.search(
        r"\b(?:sum|add|double.count|necessarily represent|additionner|somme)\b",
        normalize_text(question), re.I)) and bool(re.search(
        r"\b(?:sector|secteur)\b", normalize_text(question), re.I)))

    geo_started = time.perf_counter()
    geography = (
        resolve_geography(question)
        if source_plan["hapi"] or source_plan["fongim"] or needs_geo_inventory
        else {"region": None, "cercle": None, "assumption": None}
    )
    geography_seconds = time.perf_counter() - geo_started

    document_result = {
        "evidence": [],
        "trace": {
            "government_docs": {
                "requested": bool(source_plan["government_docs"]),
                "status": (
                    "NOT_REQUESTED"
                    if not source_plan["government_docs"]
                    else "SUCCESS_ZERO_RESULTS"
                ),
                "seconds": 0.0,
                "records": 0
            },
            "hnrp_docs": {
                "requested": bool(source_plan["hnrp_docs"]),
                "status": (
                    "NOT_REQUESTED"
                    if not source_plan["hnrp_docs"]
                    else "SUCCESS_ZERO_RESULTS"
                ),
                "seconds": 0.0,
                "records": 0
            },
            "total_seconds": 0.0
        }
    }

    hapi_result = {
        "raw_count": 0,
        "evidence": []
    }

    fongim_result = {
        "project_count": 0,
        "location_count": 0,
        "evidence": []
    }
    if count_method_question:
        fongim_result["evidence"] = [{
            "source_type": "methodology",
            "source_family": "FONGIM data model",
            "document_title": "Versioned FONGIM mirror relational schema",
            "document_type": "implementation_method",
            "organization": "Mali Knowledge Hub", "page": None,
            "section": "fongim_projects × fongim_project_sectors × fongim_project_locations",
            "content": ("The mirror joins sector and location records to projects "
                        "through fongim_project_id. One project can have multiple "
                        "sector records and multiple location records. Counts of "
                        "sector associations or project-location records are not "
                        "counts of unique projects and must not be summed. "
                        "A distinct project count requires deduplicating "
                        "fongim_project_id within the requested scope. This "
                        "schema statement does not supply a live project total.")
        }]

    source_trace = {
        "hapi": {
            "requested": bool(source_plan["hapi"]),
            "status": (
                "NOT_REQUESTED"
                if not source_plan["hapi"]
                else "SUCCESS_ZERO_RESULTS"
            ),
            "seconds": 0.0,
            "records": 0
        },
        "fongim": {
            "requested": bool(source_plan["fongim"]),
            "status": (
                "NOT_REQUESTED"
                if not source_plan["fongim"]
                else "SUCCESS_ZERO_RESULTS"
            ),
            "seconds": 0.0,
            "records": 0
        }
    }

    jobs = {}

    # Streamlit cache initialization needs the active script context. The
    # document worker can read its cached value safely after this call.
    if source_plan["government_docs"] or source_plan["hnrp_docs"]:
        get_document_groups()

    def timed_hapi():
        started = time.perf_counter()
        regions = geography.get("regions") or []
        if len(regions) > 1:
            with ThreadPoolExecutor(max_workers=min(len(regions), 4)) as region_pool:
                futures = [submit(region_pool, build_hapi_evidence,
                                  {"region": region, "cercle": None})
                           for region in regions]
                parts = [future.result() for future in futures]
            value = {
                "raw_count": sum(part["raw_count"] for part in parts),
                "evidence": [item for part in parts for item in part["evidence"]],
            }
        else:
            value = build_hapi_evidence(geography)
        return value, time.perf_counter() - started

    def timed_fongim():
        started = time.perf_counter()
        # Cache by the actual query scope, not trace-only normalization and
        # ambiguity annotations that differ from question to question.
        value = research_fongim({"region": geography.get("region"),
                                 "cercle": geography.get("cercle")})
        return value, time.perf_counter() - started

    with ThreadPoolExecutor(max_workers=3) as executor:

        if (
            source_plan["government_docs"]
            or source_plan["hnrp_docs"]
        ):
            jobs["documents"] = submit(executor,
                build_document_evidence,
                question,
                source_plan["government_docs"],
                source_plan["hnrp_docs"],
                document_count,
                document_count
            )

        if source_plan["hapi"]:
            jobs["hapi"] = submit(executor,
                timed_hapi
            )

        if source_plan["fongim"] and not count_method_question and not entity_method_question:
            jobs["fongim"] = submit(executor,
                timed_fongim
            )

        if "documents" in jobs:
            document_result = jobs["documents"].result()

        if "hapi" in jobs:
            hapi_result, hapi_seconds = jobs["hapi"].result()
            source_trace["hapi"].update({
                "status": (
                    "SUCCESS_WITH_RESULTS"
                    if hapi_result.get("evidence")
                    else "SUCCESS_ZERO_RESULTS"
                ),
                "seconds": round(hapi_seconds, 3),
                "records": int(hapi_result.get("raw_count", 0))
            })

        if "fongim" in jobs:
            fongim_result, fongim_seconds = jobs["fongim"].result()
            source_trace["fongim"].update({
                "status": (
                    "SUCCESS_WITH_RESULTS"
                    if fongim_result.get("evidence")
                    else "SUCCESS_ZERO_RESULTS"
                ),
                "seconds": round(fongim_seconds, 3),
                "records": int(fongim_result.get("project_count", 0)),
                "location_records": int(
                    fongim_result.get("location_count", 0)
                )
            })
        elif count_method_question:
            source_trace["fongim"].update({
                "status": "SUCCESS_WITH_RESULTS", "records": 1,
                "methodology_only": True
            })
        elif entity_method_question and source_plan["fongim"]:
            source_trace["fongim"].update({
                "status": "NOT_QUERIED_METHOD_QUESTION", "records": 0,
                "methodology_only": True
            })

    reduction_started = time.perf_counter()

    needs_local_inventory = bool(re.search(
        r"\b(?:local|communal|regional)\s+(?:development\s+)?(?:plan|priorit)|"
        r"\bplan\s+(?:local|communal|regional)|"
        r"\bpriorit(?:e|es|y|ies)\s+(?:local|communal|regional)",
        normalize_text(question), re.I))
    document_registry = (get_document_groups()["documents"]
                         if source_plan["government_docs"] or source_plan["hnrp_docs"]
                         or needs_local_inventory else [])
    inventory_evidence = []
    if needs_geo_inventory:
        inventory_evidence.append({
            "source_type": "geo_inventory",
            "source_family": "FONGIM geography registry",
            "document_title": "FONGIM project locations",
            "document_type": "structured_operational_data",
            "organization": "FONGIM", "page": None,
            "section": "Administrative-level candidates",
            "content": (f"Named geographic candidates in the project-location "
                        f"registry: {geography.get('normalization')}; "
                        f"homonyms across levels: {geography.get('homonyms')}. "
                        "The registry records region and cercle pairs; "
                        "commune_raw is not a verified commune entity. "
                        "A project location is not a needs estimate or coverage proof.")
        })
    if needs_entity_policy:
        inventory_evidence.append({
            "source_type": "methodology",
            "source_family": "Knowledge Hub V2 normalization method",
            "document_title": "Versioned entity-resolution registry",
            "document_type": "implementation_method",
            "organization": "Mali Knowledge Hub", "page": None,
            "section": "Organization resolution",
            "content": ("V2 preserves each original organization value and its source. "
                        "Exact distinctive names, unique normalized spellings, "
                        "and a unique acronym explicitly attached to a full "
                        "source name can resolve with a recorded method and "
                        "confidence. A bare acronym or similarity without "
                        "that evidence remains an uncertain proposal, never "
                        "an automatic merge. Reviewed decisions record "
                        "method, confidence, reviewer, rationale and decision ID. "
                        "A correction appends a superseding decision without "
                        "erasing the original decision or source value.")
        })
    if needs_local_inventory:
        titles = [str(d.get("title")) for d in document_registry if d.get("title")]
        inventory_evidence.append({
            "source_type": "corpus_inventory",
            "source_family": "Knowledge Hub corpus inventory",
            "document_title": "Current Supabase documents registry",
            "document_type": "corpus_inventory",
            "organization": "Mali Knowledge Hub",
            "page": None, "section": "Indexed document titles",
            "content": (f"The current indexed corpus contains {len(titles)} documents: "
                        + "; ".join(titles) + ". This inventory cannot prove "
                        "that no local plan exists outside the Hub.")
        })

    ledger = build_unified_evidence(
        document_result["evidence"],
        hapi_result["evidence"],
        fongim_result["evidence"] + inventory_evidence
    )
    enrich_join_evidence(ledger)
    joined = build_join_context(ledger, geography, document_registry)
    _, decisions = load_entity_decisions()
    org_resolver = OrganizationResolver(fongim_result.get("organization_names", []), decisions)
    joined["organization_resolution"] = [
        org_resolver.resolve(raw, "documents") for raw in sorted({
            str(d.get("organization")) for d in document_registry if d.get("organization")
        })
    ] if fongim_result.get("organization_names") else []

    family_counts = defaultdict(int)

    for item in ledger:
        family_counts[
            item.get("source_family")
        ] += 1

    evidence_reduction_seconds = (
        time.perf_counter() - reduction_started
    )

    execution_trace = {
        "resolved_question": question,
        "geography": {
            "resolved": geography,
            "seconds": round(geography_seconds, 3)
        },
        "routing": {
            "source_plan": source_plan,
            "planner_output": planner_result.get(
                "planner_output",
                {}
            ),
            "seconds": routing_seconds
        },
        "sources": {
            "government_docs": document_result["trace"][
                "government_docs"
            ],
            "hnrp_docs": document_result["trace"][
                "hnrp_docs"
            ],
            "hapi": source_trace["hapi"],
            "fongim": source_trace["fongim"]
        },
        "document_bundle_seconds": document_result["trace"].get(
            "total_seconds",
            0.0
        ),
        "evidence_reduction_seconds": round(
            evidence_reduction_seconds,
            3
        )
    }

    return {
        "geography": geography,
        "source_plan": source_plan,
        "ledger": ledger,
        "joined": joined,
        "family_counts": dict(family_counts),
        "hapi_raw_count": hapi_result["raw_count"],
        "fongim_project_count": fongim_result["project_count"],
        "research_seconds": round(
            time.perf_counter() - total_started,
            2
        ),
        "execution_trace": execution_trace
    }


# ============================================================
# ANSWER ENGINE
# ============================================================

def _generate_grounded_answer(
    question,
    model="gpt-5.6-luna",
    depth="balanced",
    response_language=None
):

    answer_started = time.perf_counter()

    # A deictic location without conversation context cannot be researched
    # responsibly. The UI resolves follow-ups before calling this function.
    if re.search(r"\b(there|here|that area|this area)\b|l[aà]-bas|cette zone", question, re.I):
        resolved = resolve_geography(question)
        if not resolved.get("region") and not resolved.get("cercle"):
            french = bool(re.search(r"\b(quelle|quels|qui|situation)\b|l[aà]-bas", question, re.I)) and not re.search(r"\b(what|who|there)\b", question, re.I)
            return {
                "answer": ("De quel lieu parlez-vous (région, cercle ou commune) ?"
                           if french else "Which place do you mean (region, cercle or commune)?"),
                "evidence": [], "geography": resolved,
                "source_plan": {k: False for k in ("government_docs", "hnrp_docs", "hapi", "fongim")},
                "family_counts": {}, "hapi_raw_count": 0, "fongim_project_count": 0,
                "research_seconds": 0, "synthesis_seconds": 0,
                "execution_trace": {"clarification_required": True},
                "total_seconds": round(time.perf_counter() - answer_started, 2),
            }

    PHASE.set("research")
    configuration = get_mode(depth)
    research = (
        run_four_source_research(
            question,
            document_count=configuration["document_count"]
        )
    )

    ledger = research[
        "ledger"
    ]

    evidence_text = (
        evidence_to_prompt(
            ledger
        )
    )
    joined_text = prompt_context(research["joined"])

    system_prompt = """
You are the analytical synthesis layer of the Mali Knowledge Hub.

Answer the user's question exclusively from the supplied evidence
ledger. Never use outside knowledge.

CORE RULE:
Reason across evidence. Do not reason beyond evidence.

EPISTEMIC RULES:

1. Every substantive factual claim must be supported by one or more
   exact evidence IDs, e.g. [E03] or [E03, E07].
   Cite the most direct 1–4 items for each claim. Do not use ID ranges.

2. Preserve source attribution, reference periods and geographic
   scope.

3. Never turn broader geographic evidence into a narrower geographic
   claim. If evidence is for Mopti region and the question concerns
   Bandiagara, say explicitly that it is broader regional context.
   A source paragraph can list several places after naming a region.
   Do not assign every listed place to that region unless the evidence
   explicitly states the parent relationship or the verified geography
   registry does. Keep uncertain place lists at their stated scope.
   FONGIM `commune_raw` is an unverified source label and can contain
   multiple places separated by `|`. Call it a raw location field;
   do not present its components as verified administrative communes
   or proof that services reached them.

4. Never invent facts, policies, projects, interventions, causal
   relationships, geographic aggregates, totals, rankings, coverage,
   implementation status, impact or citations.

5. Government strategy documents establish stated priorities,
   objectives, diagnoses, targets or scenarios. They do not by
   themselves demonstrate implementation or impact.

6. Humanitarian planning documents and structured humanitarian data
   must not be treated as equivalent evidence when their reference
   periods, definitions or geographic levels differ.
   A HAPI people-in-need record is a reported needs estimate; do not
   call it a directly measured prevalence or a count of people reached.

7. Never sum Admin2 observations to manufacture an Admin1 total unless
   the evidence explicitly provides such an aggregate.
   Do not state how many localities, sectors, organizations or other
   entities are in a list unless that count is explicitly supplied in
   the evidence. An unsupported count can be wrong even when every
   listed value is right.

8. FONGIM project counts describe recorded project presence. They do
   not establish funding adequacy, needs coverage, service quality,
   effectiveness or impact.

9. A FONGIM project may have multiple sectors and locations. Never sum
   sector or location counts to reconstruct the number of projects.

10. Do not infer a programming gap merely because one FONGIM sector
    has fewer recorded projects than another.

11. If a relationship across humanitarian needs, government
    priorities and operational interventions is only thematic, say
    that it is thematic rather than causal.

12. You may connect concepts across sources only when those concepts
    themselves are documented in the evidence.

13. If the evidence cannot answer part of the question, state briefly
    and precisely what cannot be established.

14. Use the language of the user's question.

15. For operational FONGIM counts, include the source's latest sync date
    when supplied. Do not imply the records are live or complete.

16. The candidate join audit is a navigation aid, not new evidence. Cite
    underlying ledger IDs from each source. Label same-sector links as
    thematic SYNTHESIS, never as proof that a project implements a plan,
    meets a need, covers a population, or delivers a result.

17. Distinguish FACT (direct source claim), SYNTHESIS (cited cross-source
    combination), and INFERENCE (tentative interpretation) where a joined
    conclusion could otherwise be mistaken for a direct fact.

18. Do not invent regional or communal plan priorities. The current
    document registry has no local plan unless explicitly listed in the
    corpus inventory. Cite its ledger ID for a statement about the Hub's
    indexed documents. Never cite the candidate join audit itself.

DEFAULT RESPONSE:
Write for a busy policy or operational adviser. Be concise,
analytical and decision-useful. Do not reproduce the evidence ledger.

Use this structure unless the question clearly requires another form:

**Bottom line**
Answer the actual question directly in 2-4 sentences.

**What the evidence shows**
Give 3-5 concise bullets with the most decision-relevant findings.
Combine related evidence instead of repeating it.

**Important limitations**
Give only 1-3 limitations that materially affect interpretation or
action. Omit this section if there are no material limitations.

LENGTH:
- Default target: 350-550 words maximum.
- Simple single-source questions: usually 150-300 words.
- Do not add separate sections called "Source facts", "Analytical
  synthesis", "Cautious inference", "Evidence limitations" or
  "Next steps" unless the user explicitly asks for that detail.
- Do not repeat the same evidence in multiple sections.
- Do not offer additional work at the end unless necessary to answer
  the question.

Citations belong directly after the claims they support. Do not add a
generic bibliography.
"""

    user_prompt = f"""
QUESTION

{question}


EVIDENCE LEDGER

{evidence_text}

{joined_text}

{intersectoral_locality_note(ledger)}


Produce a concise evidence-grounded analytical answer.
Write the entire answer in {response_language or answer_language(question)}. The evidence may be
in a different language; translate faithfully while retaining citations.
"""

    synthesis_started = time.perf_counter()

    PHASE.set("synthesis")
    response = (
        openai_client
        .responses
        .create(
            model=model,
            reasoning={"effort": "none"},
            max_output_tokens=configuration["max_output_tokens"],
            instructions=system_prompt,
            input=user_prompt
        )
    )

    return {
        "answer":
            response.output_text,

        "evidence":
            ledger,

        "joined": research["joined"],

        "geography":
            research[
                "geography"
            ],

        "source_plan":
            research[
                "source_plan"
            ],

        "family_counts":
            research[
                "family_counts"
            ],

        "hapi_raw_count":
            research[
                "hapi_raw_count"
            ],

        "fongim_project_count":
            research[
                "fongim_project_count"
            ],

        "research_seconds":
            research.get(
                "research_seconds"
            ),

        "synthesis_seconds":
            round(
                time.perf_counter()
                - synthesis_started,
                2
            ),

        "execution_trace":
            research.get(
                "execution_trace",
                {}
            ),

        "total_seconds":
            round(
                time.perf_counter()
                - answer_started,
                2
            )
    }


def generate_grounded_answer(question, model="gpt-5.6-luna", depth=None, response_language=None):
    depth = depth or os.environ.get("MKH_DEPTH", "balanced")
    token, query_id = openai_client.begin()
    try:
        result = _generate_grounded_answer(question, model=model, depth=depth,
                                           response_language=response_language)
    except Exception as exc:
        usage = openai_client.finish(token, query_id)
        # Record only a class and frame names. Provider errors can include
        # request content or credentials and must not enter service logs.
        print("MKH_FAILURE " + json.dumps({
            "request_id": query_id, "depth": depth,
            "error_type": type(exc).__name__,
            "frames": [frame.name for frame in traceback.extract_tb(exc.__traceback__)[-6:]],
            "api_usage": usage,
        }, separators=(",", ":")))
        raise
    else:
        usage = openai_client.finish(token, query_id)
    result["api_usage"] = usage
    result["request_id"] = query_id
    result["depth"] = depth
    result["answer"], result["citation_audit"] = verify_citations(
        result["answer"], result["evidence"])
    if not result["citation_audit"]["valid"]:
        result["answer"] = (
            "I could not verify the generated answer's evidence citations. "
            "Please retry the question; no uncited factual answer is shown."
        )
    print("MKH_USAGE " + json.dumps({
        "request_id": query_id, "depth": depth,
        "total_seconds": result.get("total_seconds"),
        "source_plan": result.get("source_plan"),
        "join_count": len(result.get("joined", {}).get("relationships", [])),
        "citation_valid": result["citation_audit"]["valid"],
        "api_usage": usage,
    }, separators=(",", ":")), flush=True)
    return result


# ============================================================
# CONVERSATIONAL CONTEXT
# ============================================================

def likely_context_dependent_followup(
    question,
    messages
):

    if not messages:
        return False

    q = normalize_text(question).strip()

    if not q:
        return False

    markers = [
        "what about ",
        "how about ",
        "and ",
        "but ",
        "compare that",
        "compare this",
        "compare it",
        "same for ",
        "same question",
        "that ",
        "this ",
        "those ",
        "these ",
        "them ",
        "it ",
        "why is that",
        "why does that",
        "what does that",
        "and there",
        "and in ",
        "et ",
        "mais ",
        "meme question",
        "et la-bas",
        "dans cette zone",
        "compare cela",
        "compare ca",
    ]

    if any(
        q.startswith(marker)
        for marker in markers
    ):
        return True

    return len(q.split()) <= 5


def resolve_conversational_question(
    question,
    messages,
    model="gpt-5-mini"
):
    """Convert a follow-up into a standalone research question."""

    prior_turns = []
    for message in messages[-10:]:
        role = message.get("role")
        if role == "user":
            value = message.get("standalone_question") or message.get("content")
            if value:
                prior_turns.append(f"USER QUESTION: {str(value)[:1200]}")
        elif role == "assistant" and message.get("content"):
            # An answer can establish what "that finding" refers to. It is
            # query context only; the new analysis retrieves fresh evidence.
            prior_turns.append(f"ASSISTANT CONTEXT ONLY: {str(message['content'])[:1200]}")

    if not prior_turns:
        return question.strip()

    context_text = "\n\n".join(prior_turns[-8:])

    instructions = """
You rewrite conversational follow-up questions for an evidence-grounded
research system.

Use the previous exchange only to resolve conversational references.
An earlier assistant answer may identify the topic or entity the user means,
but it is never evidence that a claim is true.

Return ONE standalone research question that preserves the user's intent.

Rules:
1. Do not answer the question.
2. Mention an entity from the prior exchange only when needed to resolve a
   reference. Phrase any prior assistant claim as something to investigate,
   never as an established fact or premise.
3. Do not use outside knowledge.
4. Never cite or rely on a previous assistant answer as evidence. The new
   question will trigger fresh retrieval from documents and data.
5. If the new question is already standalone, return it essentially unchanged.
6. Use the language of the new question.
7. Return only the rewritten question.
"""

    input_text = f"""
PREVIOUS CONVERSATION (CONTEXT, NOT EVIDENCE)

{context_text}

NEW USER QUESTION

{question}
"""

    response = (
        openai_client
        .responses
        .create(
            model=model,
            instructions=instructions,
            input=input_text
        )
    )

    return (
        response.output_text
        or question
    ).strip()


# ============================================================
# USER INTERFACE
# ============================================================

st.markdown(
    """
<style>
    .stApp {
        background: #fbfdfc;
        color: #193b38;
    }

    .block-container {
        max-width: 900px;
        padding-top: 1.55rem;
        padding-bottom: 7.5rem;
    }

    .kh-hero {
        padding: 0 0 1.05rem;
        margin-bottom: 0.4rem;
        border-bottom: 1px solid #dcebe7;
    }

    .kh-title {
        font-size: 1.38rem;
        line-height: 1.2;
        font-weight: 760;
        letter-spacing: -0.025em;
        margin: 0 0 0.2rem;
        color: #104844;
    }

    .kh-subtitle {
        font-size: 0.83rem;
        line-height: 1.4;
        color: #647d78;
        margin: 0;
    }

    .kh-welcome {
        margin: 5vh auto 1.25rem;
        max-width: 690px;
        text-align: center;
    }

    .kh-welcome h1 {
        font-size: clamp(1.7rem, 3vw, 2.45rem);
        line-height: 1.2;
        letter-spacing: -0.04em;
        color: #143f3a;
        margin-bottom: 0.5rem;
    }

    .kh-welcome p {
        color: #627b76;
        font-size: 1rem;
        margin: 0;
    }

    .kh-search-label {
        font-size: 0.93rem;
        font-weight: 780;
        color: #245b56;
        margin: 0.65rem 0 0.38rem 0;
    }

    .kh-examples-label {
        font-size: 0.92rem;
        font-weight: 760;
        color: #315e5a;
        margin-top: 1.15rem;
        margin-bottom: 0.35rem;
    }

    .kh-example-card {
        border: 1px solid #d1e7e3;
        border-radius: 15px;
        padding: 0.85rem;
        min-height: 112px;
        background: #ffffff;
        margin-bottom: 0.25rem;
    }

    .kh-example-kicker {
        font-size: 0.8rem;
        font-weight: 850;
        letter-spacing: 0.04em;
        color: #087f78;
        margin-bottom: 0.48rem;
    }

    .kh-example-text {
        font-size: 0.9rem;
        line-height: 1.42;
        color: #164a46;
        min-height: 58px;
    }

    .kh-how-copy {
        color: #667e79;
        font-size: 0.92rem;
        margin-top: -0.1rem;
        margin-bottom: 0.55rem;
    }

    .kh-section-intro {
        margin: 1.45rem 0 0.45rem 0;
        color: #436c66;
        font-size: 0.9rem;
        font-weight: 680;
    }

    div[data-testid="stTextArea"] textarea {
        min-height: 92px !important;
        border-radius: 16px !important;
        border: 1.5px solid #a7d9d2 !important;
        background: #ffffff !important;
        font-size: 1.05rem !important;
        line-height: 1.45 !important;
        padding: 1rem 1.05rem !important;
        box-shadow: 0 4px 18px rgba(8, 127, 120, 0.06);
    }

    div[data-testid="stTextArea"] textarea:focus {
        border-color: #087f78 !important;
        box-shadow: 0 0 0 3px rgba(8, 127, 120, 0.10) !important;
    }

    div[data-testid="stExpander"] {
        border: 1px solid #d2e5e1 !important;
        border-radius: 16px !important;
        background: linear-gradient(180deg, #ffffff 0%, #f8fcfb 100%) !important;
        box-shadow: 0 5px 18px rgba(14, 83, 76, 0.045);
        margin-bottom: 0.8rem;
        overflow: hidden;
    }

    div[data-testid="stExpander"] details > summary {
        min-height: 68px;
        padding: 0.75rem 1rem !important;
    }

    div[data-testid="stExpander"] details > summary p {
        font-size: 1.08rem !important;
        font-weight: 780 !important;
        color: #164d48 !important;
    }

    div[data-testid="stChatMessage"] {
        border-radius: 16px;
        padding: 0.25rem 0.4rem;
        margin-bottom: 0.55rem;
    }

    div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        background: #edf7f4;
    }

    div[data-testid="stChatInput"] textarea {
        font-size: 1rem;
    }

    button[kind="primary"] {
        background: #087f78 !important;
        border-color: #087f78 !important;
        color: white !important;
        border-radius: 12px;
        font-weight: 700;
        min-height: 46px;
    }

    button[kind="primary"]:hover {
        background: #086d67 !important;
        border-color: #086d67 !important;
    }

    .kh-topnav {
        display: none;
    }

    [data-testid="stChatInput"] {
        max-width: 900px;
        margin-left: auto;
        margin-right: auto;
    }

    [data-testid="stChatInput"] > div {
        border: 1.5px solid #a7d7d0 !important;
        border-radius: 20px !important;
        background: #ffffff !important;
        box-shadow: 0 6px 24px rgba(8, 88, 81, 0.10) !important;
    }

    [data-testid="stChatInput"] > div:focus-within {
        border-color: #086d67 !important;
        box-shadow: 0 0 0 3px rgba(8,127,120,.10), 0 6px 20px rgba(8,127,120,.13) !important;
    }

    @media (max-width: 760px) {
        .block-container {
            padding-top: 1.15rem;
        }

        .kh-title {
            font-size: 1.2rem;
        }

        .kh-subtitle {
            font-size: 0.78rem;
        }

        .kh-welcome {
            margin-top: 2vh;
        }
    }
</style>

<div class="kh-hero">
    <div class="kh-title">Mali Knowledge Hub</div>
    <div class="kh-subtitle">
        Evidence-based analysis for humanitarian, development and peace work in Mali
    </div>
</div>
""",
    unsafe_allow_html=True
)


user_auth = (create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
             if SUPABASE_PUBLISHABLE_KEY else None)
user_token = st.session_state.get("mkh_user_token")
user_callback = st.components.v2.component(
    name="mkh_user_magic_link_callback",
    js="""
    export default function({ data, setTriggerValue }) {
      if (window.location.pathname !== "/") return;
      const key = "mkh_user_access_token";
      if (data.clear) {
        window.sessionStorage.removeItem(key);
        return;
      }
      const fragment = window.location.hash.slice(1);
      const token = fragment ? new URLSearchParams(fragment).get("access_token") : null;
      if (token) {
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
        window.sessionStorage.setItem(key, token);
        setTriggerValue("access_token", token);
      } else if (data.needs_restore) {
        const restored = window.sessionStorage.getItem(key);
        if (restored) setTriggerValue("access_token", restored);
      }
    }
    """,
)
callback = user_callback(
    key="mkh_user_magic_link_callback",
    data={"clear": st.session_state.pop("mkh_user_clear_token", False),
          "needs_restore": not user_token},
)
if callback.get("access_token") and user_auth:
    candidate = callback["access_token"]
    try:
        verified = user_auth.auth.get_user(candidate).user
        if verified and verified.id:
            st.session_state["mkh_user_token"] = candidate
            user_token = candidate
        else:
            raise ValueError("invalid user")
    except Exception:
        st.session_state["mkh_user_clear_token"] = True
        st.session_state["mkh_user_error"] = "The sign-in link has expired. Request a new one."
        st.rerun()

current_user = None
if user_token and user_auth:
    try:
        current_user = user_auth.auth.get_user(user_token).user
    except Exception:
        current_user = None
    if not current_user:
        st.session_state.pop("mkh_user_token", None)
        st.session_state["mkh_user_clear_token"] = True
        st.rerun()

research_store = (ResearchStore(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY,
                                user_token, current_user.id)
                  if current_user else None)


def new_thread():
    thread_id = str(uuid.uuid4())
    st.session_state["kh_threads"][thread_id] = {
        "title": "New conversation", "messages": [], "depth": "balanced",
        "updated_at": datetime.now(timezone.utc).isoformat(), "archived": False,
        "persisted": False, "loaded": True,
        "saved_messages": 0,
    }
    st.session_state["kh_active_thread"] = thread_id
    st.session_state["kh_messages"] = st.session_state["kh_threads"][thread_id]["messages"]


def load_private_messages(thread_id):
    thread = st.session_state["kh_threads"][thread_id]
    if not research_store or thread.get("loaded"):
        return
    rows = research_store.list_messages(thread_id)
    thread["messages"] = [{
        "role": row["role"], "content": row["content"],
        "standalone_question": row.get("standalone_question"),
        "analysis_mode": row.get("analysis_mode") or "balanced",
        "result": ({"evidence": row.get("evidence_refs") or [],
                    "family_counts": dict(Counter(
                        ref.get("source_family") for ref in (row.get("evidence_refs") or []))),
                    "saved": True}
                   if row["role"] == "assistant" else None),
    } for row in rows]
    thread["saved_messages"] = len(rows)
    thread["loaded"] = True


def sync_private_thread(thread_id):
    if not research_store:
        return
    thread = st.session_state["kh_threads"][thread_id]
    if not thread["persisted"]:
        try:
            research_store.create_conversation(thread_id, thread["title"], thread["depth"])
        except ResearchStoreError:
            # Recover a create that committed before the HTTP response failed.
            if not any(row["id"] == thread_id for row in research_store.list_conversations()):
                raise
        thread["persisted"] = True
    messages = thread["messages"]
    while thread["saved_messages"] + 1 < len(messages):
        offset = thread["saved_messages"]
        question, answer = messages[offset:offset + 2]
        if question["role"] != "user" or answer["role"] != "assistant":
            raise ResearchStoreError("Unexpected conversation sequence.")
        research_store.save_exchange(
            thread_id, offset + 1, question["content"],
            question.get("standalone_question") or question["content"],
            answer["content"], question.get("analysis_mode") or thread["depth"],
            evidence_references(answer.get("result") or {}),
        )
        thread["saved_messages"] += 2


identity = current_user.id if current_user else "guest"
if st.session_state.get("kh_identity") != identity:
    # A guest's local messages are never silently adopted by an account.
    st.session_state["kh_threads"] = {}
    st.session_state["kh_active_thread"] = None
    st.session_state["kh_identity"] = identity
    if research_store:
        try:
            for row in research_store.list_conversations():
                st.session_state["kh_threads"][row["id"]] = {
                    "title": row["title"], "messages": [],
                    "depth": row["analysis_mode"],
                    "updated_at": row["updated_at"],
                    "archived": bool(row["archived_at"]),
                    "persisted": True, "loaded": False,
                    "saved_messages": 0,
                }
            recent = [(tid, item) for tid, item in st.session_state["kh_threads"].items()
                      if not item["archived"]]
            if recent:
                st.session_state["kh_active_thread"] = recent[0][0]
        except ResearchStoreError:
            st.session_state["mkh_user_error"] = "Saved conversations are temporarily unavailable."
if "kh_threads" not in st.session_state:
    st.session_state["kh_threads"] = {}
if st.session_state.get("kh_active_thread") not in st.session_state["kh_threads"]:
    new_thread()
try:
    load_private_messages(st.session_state["kh_active_thread"])
except ResearchStoreError:
    st.session_state["kh_threads"][st.session_state["kh_active_thread"]]["load_error"] = True
    st.session_state["mkh_user_error"] = "This conversation could not be loaded."
st.session_state["kh_messages"] = st.session_state["kh_threads"][
    st.session_state["kh_active_thread"]]["messages"]

if "kh_page" not in st.session_state:
    st.session_state["kh_page"] = "Knowledge Hub"


def reset_conversation():
    if st.session_state["kh_messages"]:
        new_thread()


def render_execution_trace(result):

    trace = result.get("execution_trace") or {}

    if not trace:
        return

    with st.expander("🧪 Retrieval trace"):

        geography_trace = trace.get("geography", {})
        routing_trace = trace.get("routing", {})
        sources = trace.get("sources", {})

        st.markdown("**Resolved question**")
        st.code(
            trace.get("resolved_question", ""),
            language=None
        )

        resolved_geo = geography_trace.get("resolved", {})

        st.markdown("**Resolved geography**")
        st.json(resolved_geo)

        st.markdown("**Source plan**")
        st.json(
            routing_trace.get("source_plan", {})
        )

        planner_output = routing_trace.get(
            "planner_output",
            {}
        )

        if planner_output:
            st.markdown("**Structured planner output**")
            st.json(planner_output)

        st.markdown("**Source execution**")

        source_rows = []

        labels = {
            "government_docs": "Government documents",
            "hnrp_docs": "HNRP",
            "hapi": "OCHA / HAPI",
            "fongim": "FONGIM"
        }

        for key in [
            "government_docs",
            "hnrp_docs",
            "hapi",
            "fongim"
        ]:
            item = sources.get(key, {})

            source_rows.append({
                "Source": labels[key],
                "Status": item.get(
                    "status",
                    "UNKNOWN"
                ),
                "Records": item.get(
                    "records",
                    0
                ),
                "Seconds": item.get(
                    "seconds",
                    0.0
                )
            })

        st.dataframe(
            source_rows,
            width="stretch",
            hide_index=True
        )

        st.markdown("**Pipeline timing**")

        total_seconds = result.get("total_seconds", 0.0)
        research_seconds = result.get("research_seconds", 0.0)
        synthesis_seconds = result.get("synthesis_seconds", 0.0)

        timing_rows = [
            {
                "Stage": "Geography resolution",
                "Seconds": geography_trace.get(
                    "seconds",
                    0.0
                )
            },
            {
                "Stage": "Source routing",
                "Seconds": routing_trace.get(
                    "seconds",
                    0.0
                )
            },
            {
                "Stage": "Government retrieval",
                "Seconds": sources.get(
                    "government_docs",
                    {}
                ).get(
                    "seconds",
                    0.0
                )
            },
            {
                "Stage": "HNRP retrieval",
                "Seconds": sources.get(
                    "hnrp_docs",
                    {}
                ).get(
                    "seconds",
                    0.0
                )
            },
            {
                "Stage": "HAPI",
                "Seconds": sources.get(
                    "hapi",
                    {}
                ).get(
                    "seconds",
                    0.0
                )
            },
            {
                "Stage": "FONGIM",
                "Seconds": sources.get(
                    "fongim",
                    {}
                ).get(
                    "seconds",
                    0.0
                )
            },
            {
                "Stage": "Evidence normalization",
                "Seconds": trace.get(
                    "evidence_reduction_seconds",
                    0.0
                )
            },
            {
                "Stage": "Total research wall time",
                "Seconds": research_seconds
            },
            {
                "Stage": "Final synthesis",
                "Seconds": synthesis_seconds
            },
            {
                "Stage": "Total response",
                "Seconds": total_seconds
            }
        ]

        st.dataframe(
            timing_rows,
            width="stretch",
            hide_index=True
        )

        st.caption(
            "Source calls execute in parallel where possible, so "
            "individual source times do not sum to research wall time."
        )

        usage = result.get("api_usage") or {}
        if usage:
            st.markdown("**OpenAI usage and estimated cost**")
            st.caption(
                f"{usage.get('call_count', 0)} calls · "
                f"{usage.get('input_tokens', 0)} input tokens · "
                f"{usage.get('output_tokens', 0)} output tokens · "
                f"approximately US${usage.get('estimated_usd', 0):.5f}"
            )
            st.dataframe(usage.get("calls", []), width="stretch", hide_index=True)
        citation_audit = result.get("citation_audit")
        if citation_audit:
            st.caption(
                f"Citation check: {'passed' if citation_audit['valid'] else 'failed'} · "
                f"{len(citation_audit['cited_ids'])} cited evidence IDs"
            )


def render_source_summary(result):

    family_counts = result.get("family_counts", {})

    source_labels = [
        "Government strategies",
        "Humanitarian Response Plan / HNRP",
        "Humanitarian reports and appeals",
        "OCHA humanitarian data",
        "FONGIM intervention data"
    ]

    used = []

    for family in source_labels:
        count = family_counts.get(family, 0)

        if count:
            used.append(f"**{family}** · {count}")

    if used:
        st.markdown(" · ".join(used))

    if result.get("hapi_raw_count"):
        st.caption(
            "OCHA: "
            f"{result['hapi_raw_count']} source records reduced to the "
            "relevant evidence set while preserving the documented "
            "geographic structure."
        )

    if result.get("fongim_project_count"):
        st.caption(
            "FONGIM: "
            f"{result['fongim_project_count']} unique projects matched "
            "the selected geographic scope. Project presence does not "
            "by itself establish coverage or impact."
        )


def render_evidence_inspector(result, key_prefix):

    with st.expander("Inspect evidence"):

        if result.get("saved") and not result.get("passages_loaded") and any(
            ref.get("chunk_id") is not None for ref in result.get("evidence", [])
        ):
            if st.button("Load document passages", key=f"passages_{key_prefix}"):
                try:
                    hydrate_saved_evidence(
                        result,
                        lambda ids: (supabase.table("chunks").select("id,content")
                                     .in_("id", ids).execute().data or []),
                    )
                except Exception:
                    st.warning("Document passages could not be loaded. Try again.")

        for item in result.get("evidence", []):

            page = (
                f" · p. {item['page']}"
                if item.get("page") is not None
                else ""
            )

            label = (
                f"{item['evidence_id']} — "
                f"{item.get('source_family')}"
                f"{page}"
            )

            with st.expander(label):

                if item.get("document_title"):
                    st.markdown(
                        "**Source:** "
                        f"{item['document_title']}"
                    )

                if item.get("organization"):
                    st.markdown(
                        "**Organization:** "
                        f"{item['organization']}"
                    )

                if item.get("section"):
                    st.markdown(
                        "**Section / dimension:** "
                        f"{item['section']}"
                    )

                if item.get("version"):
                    st.markdown(
                        "**Version:** "
                        f"{item['version']}"
                    )

                if item.get("publication_date"):
                    st.markdown(f"**Publication date:** {item['publication_date']}")
                if item.get("valid_from") or item.get("valid_until"):
                    st.markdown(
                        f"**Validity:** {item.get('valid_from') or 'unknown'} to "
                        f"{item.get('valid_until') or 'unknown'}"
                    )
                if item.get("geographic_scope"):
                    st.markdown(f"**Geographic scope:** {item['geographic_scope']}")

                passage = item.get("content") or item.get("source_excerpt")
                if passage:
                    st.markdown("**Evidence:**")
                    st.write(passage)
                    if result.get("saved") and item.get("source_excerpt"):
                        st.caption("Saved structured evidence snapshot. Ask again to refresh the underlying data.")
                elif result.get("saved") and item.get("chunk_id") is not None and not result.get("passages_loaded"):
                    st.caption("Load document passages above to inspect this source.")
                elif result.get("saved"):
                    st.caption("Source reference retained; the passage is no longer in the current corpus. Ask again to refresh it.")


with st.sidebar:
    st.caption("MALI KNOWLEDGE HUB")
    if notice := st.session_state.pop("mkh_user_error", None):
        st.warning(notice)
    if current_user:
        st.caption(f"Signed in · {current_user.email}")
        if st.button("Sign out", width="stretch"):
            st.session_state.pop("mkh_user_token", None)
            st.session_state["mkh_user_clear_token"] = True
            st.rerun()
    elif user_auth:
        with st.popover("Sign in to save research", width="stretch"):
            st.write("Guest research is available immediately. Create an account or sign in with an email link to keep conversations across sessions.")
            email = st.text_input("Email address", key="mkh_user_email").strip().casefold()
            if st.button("Email me a sign-in link", disabled=not email):
                try:
                    user_auth.auth.sign_in_with_otp({
                        "email": email,
                        "options": {"should_create_user": True,
                                    "email_redirect_to": "https://mali-knowledge-hub.onrender.com/"},
                    })
                    st.info("Check your inbox and open the sign-in link in this browser.")
                except Exception:
                    st.error("The sign-in link could not be sent. Please try again later.")
    if st.button("New chat", type="primary", width="stretch", key="nav_new_chat"):
        reset_conversation()
        st.session_state["kh_page"] = "Knowledge Hub"
        st.rerun()

    active_thread = st.session_state["kh_threads"][st.session_state["kh_active_thread"]]
    mode_labels = {"quick": "Quick — faster, narrower",
                   "balanced": "Balanced — default",
                   "deep": "Deep — broader and more thorough"}
    selected_depth = st.selectbox(
        "Analysis depth", list(mode_labels),
        index=list(mode_labels).index(active_thread["depth"]),
        format_func=lambda mode: mode_labels[mode],
        key=f"kh_depth_{st.session_state['kh_active_thread']}",
    )
    active_thread["depth"] = selected_depth

    st.caption("RECENT CONVERSATIONS")
    for thread_id, thread in sorted(st.session_state["kh_threads"].items(),
                                    key=lambda item: item[1]["updated_at"], reverse=True):
        if thread.get("archived"):
            continue
        label = thread["title"][:42] + ("…" if len(thread["title"]) > 42 else "")
        if st.button(label, key=f"thread_{thread_id}", width="stretch",
                     disabled=thread_id == st.session_state["kh_active_thread"]):
            st.session_state["kh_active_thread"] = thread_id
            st.session_state["kh_page"] = "Knowledge Hub"
            st.rerun()

    with st.popover("Conversation options", width="stretch"):
        renamed = st.text_input("Title", value=active_thread["title"],
                                key=f"rename_{st.session_state['kh_active_thread']}")
        if st.button("Rename", key="rename_active") and renamed.strip():
            try:
                if research_store and active_thread["persisted"]:
                    research_store.update_conversation(st.session_state["kh_active_thread"],
                                                       title=renamed.strip()[:120])
                active_thread["title"] = renamed.strip()[:120]
                active_thread["updated_at"] = datetime.now(timezone.utc).isoformat()
                st.rerun()
            except ResearchStoreError:
                st.error("The title could not be saved.")
        if st.button("Archive", key="archive_active"):
            try:
                if research_store and active_thread["persisted"]:
                    research_store.update_conversation(
                        st.session_state["kh_active_thread"],
                        archived_at=datetime.now(timezone.utc).isoformat())
                active_thread["archived"] = True
                new_thread()
                st.rerun()
            except ResearchStoreError:
                st.error("The conversation could not be archived.")
        confirm_delete = st.checkbox("Permanently delete this conversation",
                                     key=f"confirm_delete_{st.session_state['kh_active_thread']}")
        if st.button("Delete", key="delete_active", disabled=not confirm_delete):
            try:
                if research_store and active_thread["persisted"]:
                    research_store.delete_conversation(st.session_state["kh_active_thread"])
                del st.session_state["kh_threads"][st.session_state["kh_active_thread"]]
                new_thread()
                st.rerun()
            except ResearchStoreError:
                st.error("The conversation could not be deleted.")

    archived = [(tid, item) for tid, item in st.session_state["kh_threads"].items()
                if item.get("archived")]
    if archived:
        with st.expander(f"Archived ({len(archived)})"):
            for thread_id, thread in archived:
                if st.button(f"Restore · {thread['title'][:35]}", key=f"restore_{thread_id}"):
                    try:
                        if research_store and thread["persisted"]:
                            research_store.update_conversation(thread_id, archived_at=None)
                        thread["archived"] = False
                        st.session_state["kh_active_thread"] = thread_id
                        st.session_state["kh_page"] = "Knowledge Hub"
                        st.rerun()
                    except ResearchStoreError:
                        st.error("The conversation could not be restored.")

    st.divider()
    st.caption("EXPLORE")

    if st.button("How it works", width="stretch", key="nav_how"):
        st.session_state["kh_page"] = "How it works"
        st.rerun()

    if st.button("Available sources", width="stretch", key="nav_sources"):
        st.session_state["kh_page"] = "Available sources"
        st.rerun()

    st.page_link("pages/1_Administration.py", label="Administration",
                 width="stretch")

    if not current_user:
        st.caption("Guest mode · conversations last for this browser session.")
    else:
        st.caption("Private research · saved to your account.")

if st.session_state["kh_page"] == "How it works":
    with st.container(border=False):

        st.markdown(
            '<div class="kh-how-copy">From your question to an evidence-based answer — in 6 steps</div>',
            unsafe_allow_html=True
        )

        step1, step2, step3 = st.columns(3, gap="medium")

        with step1:
            st.markdown(
                """
    **1 · Understand**
    The Hub identifies the geography, topic and types of evidence needed.

    **2 · Retrieve**
    It searches the document corpus and, where relevant, queries live OCHA data and structured FONGIM records.
    """
            )

        with step2:
            st.markdown(
                """
    **3 · Select**
    Only relevant passages and structured records are passed into the analysis. The AI does not answer from general knowledge.

    **4 · Preserve**
    Geographic levels, reporting periods, source categories and source limitations are retained instead of being silently merged.
    """
            )

        with step3:
            st.markdown(
                """
    **5 · Analyse**
    The AI compares evidence across sources to identify documented alignments, gaps and tensions.

    **6 · Respond**
    The answer is generated with evidence references, and the underlying evidence items remain inspectable.
    """
            )

        st.info(
            "The AI interprets retrieved evidence. It is not itself the source of truth."
        )

        st.caption(
            "Core rule: Reason across evidence. Do not reason beyond evidence."
        )

elif st.session_state["kh_page"] == "Available sources":
    with st.container(border=False):

        st.caption(
            "Explore the documents and structured data currently integrated in the Knowledge Hub."
        )

        source_col1, source_col2 = st.columns(2, gap="large")

        with source_col1:

            st.markdown(
                """
    <div class="kh-example-card">
        <div class="kh-example-kicker">🏛️ GOVERNMENT FRAMEWORK DOCUMENTS</div>
        <div class="kh-example-text">
            National, regional, local and sectoral strategies and plans
        </div>
    </div>
    """,
                unsafe_allow_html=True
            )

            with st.popover(
                "View available documents",
                width="stretch"
            ):
                st.markdown(
                    """
    - **Vision Mali 2063 — Mali Kura Ɲɛtaasira ka bɛn san 2063 ma**
    - **Stratégie Nationale pour l’Émergence et le Développement Durable (SNEDD 2024–2033)**
    - **Projets Structurants Prioritaires pour la mise en œuvre de Mali Kura 2063 et de la SNEDD 2024–2033**
    - **Phasage des Projets Structurants Prioritaires**
    """
                )

            st.markdown(
                """
    <div class="kh-example-card">
        <div class="kh-example-kicker">👥 HUMANITARIAN NEEDS ASSESSMENT</div>
        <div class="kh-example-text">
            Humanitarian needs and response planning documents
        </div>
    </div>
    """,
                unsafe_allow_html=True
            )

            with st.popover(
                "View available documents",
                width="stretch"
            ):
                st.markdown(
                    """
    - **Mali — Besoins humanitaires et Plan de Réponse 2026**
    """
                )

        with source_col2:

            st.markdown(
                """
    <div class="kh-example-card">
        <div class="kh-example-kicker">🗄️ OCHA DATABASE</div>
        <div class="kh-example-text">
            Live structured humanitarian needs data via HDX HAPI
        </div>
    </div>
    """,
                unsafe_allow_html=True
            )

            st.link_button(
                "Go to HDX HAPI ↗",
                "https://hapi.humdata.org/",
                width="stretch"
            )

            st.markdown(
                """
    <div class="kh-example-card">
        <div class="kh-example-kicker">🌐 INTERNATIONAL NGO ACTIVITIES</div>
        <div class="kh-example-text">
            Structured project information through the FONGIM database
        </div>
    </div>
    """,
                unsafe_allow_html=True
            )

            st.link_button(
                "Open FONGIM interactive map ↗",
                "https://www.fongim.org/carte-interactive",
                width="stretch"
            )

else:
    example_prompt = None

    if not st.session_state["kh_messages"]:

        st.markdown(
            '<div class="kh-welcome"><h1>What would you like to explore?</h1>'
            '<p>Ask about needs, priorities, projects and organisations across Mali. '
            'Answers link back to the evidence.</p></div>',
            unsafe_allow_html=True
        )

        st.markdown(
            '<div class="kh-examples-label">Start with a question</div>',
            unsafe_allow_html=True
        )

        example_col1, example_col2, example_col3 = st.columns(
            3,
            gap="medium"
        )

        with example_col1:
            st.markdown(
                """
    <div class="kh-example-card">
        <div class="kh-example-kicker">🔎 SEARCH</div>
        <div class="kh-example-text">
            What are the Government's priorities for local development
            in Kayes?
        </div>
    </div>
    """,
                unsafe_allow_html=True
            )

            if st.button(
                "Ask this →",
                key="example_search",
                width="stretch"
            ):
                example_prompt = (
                    "What are the Government's priorities for local "
                    "development in Kayes?"
                )

        with example_col2:
            st.markdown(
                """
    <div class="kh-example-card">
        <div class="kh-example-kicker">↔ COMPARE</div>
        <div class="kh-example-text">
            In Mopti, how do humanitarian needs compare with current
            NGO interventions?
        </div>
    </div>
    """,
                unsafe_allow_html=True
            )

            if st.button(
                "Ask this →",
                key="example_compare",
                width="stretch"
            ):
                example_prompt = (
                    "In Mopti, how do humanitarian needs compare with "
                    "current NGO interventions?"
                )

        with example_col3:
            st.markdown(
                """
    <div class="kh-example-card">
        <div class="kh-example-kicker">💡 ANALYSE &amp; PLAN</div>
        <div class="kh-example-text">
            Where are the main gaps and opportunities for stronger
            Humanitarian-Development-Peace coordination in Gao?
        </div>
    </div>
    """,
                unsafe_allow_html=True
            )

            if st.button(
                "Ask this →",
                key="example_plan",
                width="stretch"
            ):
                example_prompt = (
                    "Where are the main gaps and opportunities for stronger "
                    "Humanitarian-Development-Peace coordination in Gao?"
                )
    else:

        for message_index, message in enumerate(st.session_state["kh_messages"]):

            if message.get("role") == "user":

                with st.chat_message("user"):
                    st.markdown(
                        message.get("content", "")
                    )

            elif message.get("role") == "assistant":

                with st.chat_message("assistant"):

                    st.markdown(
                        message.get("content", "")
                    )

                    result = message.get("result")

                    if result:

                        geography = result.get("geography", {})

                        if geography.get("assumption"):
                            st.info(
                                geography["assumption"]
                            )

                        with st.expander("Sources used"):
                            render_source_summary(result)

                            if result.get("total_seconds") is not None:
                                st.caption(
                                    "Response time: "
                                    f"{result['total_seconds']:.1f}s "
                                    "· source research: "
                                    f"{result.get('research_seconds', 0):.1f}s"
                                )

                        if os.environ.get("MKH_SHOW_RETRIEVAL_TRACE") == "1":
                            render_execution_trace(result)
                        render_evidence_inspector(
                            result,
                            f"{st.session_state['kh_active_thread']}_{message_index}",
                        )

    active_thread = st.session_state["kh_threads"][st.session_state["kh_active_thread"]]
    if research_store and active_thread["saved_messages"] < len(active_thread["messages"]):
        st.warning("This conversation has changes that have not been saved to your account.")
        if st.button("Retry saving"):
            try:
                sync_private_thread(st.session_state["kh_active_thread"])
                st.rerun()
            except ResearchStoreError:
                st.error("Saving is unavailable. Your messages remain in this browser session.")

    active_thread = st.session_state["kh_threads"][st.session_state["kh_active_thread"]]
    if active_thread.get("load_error"):
        st.error("This saved conversation could not be loaded. Try again before continuing it.")
        if st.button("Retry loading conversation"):
            active_thread.pop("load_error", None)
            st.rerun()

    typed_prompt = st.chat_input(
        "Ask about Mali's needs, priorities and interventions...",
        disabled=bool(active_thread.get("load_error")),
    )

    current_prompt = typed_prompt or example_prompt


    if current_prompt:

        current_prompt = current_prompt.strip()

        if current_prompt:
            active_thread = st.session_state["kh_threads"][st.session_state["kh_active_thread"]]
            if not active_thread["messages"]:
                active_thread["title"] = current_prompt[:80]
            active_thread["updated_at"] = datetime.now(timezone.utc).isoformat()

            prior_messages = list(
                st.session_state[
                    "kh_messages"
                ]
            )

            st.session_state[
                "kh_messages"
            ].append(
                {
                    "role": "user",
                    "content": current_prompt,
                    "standalone_question": current_prompt,
                    "analysis_mode": active_thread["depth"],
                }
            )

            if is_source_inventory_question(
                current_prompt
            ):

                st.session_state[
                    "kh_messages"
                ].append(
                    {
                        "role": "assistant",
                        "content": source_inventory_answer(),
                        "analysis_mode": active_thread["depth"],
                        "result": None
                    }
                )

            else:

                standalone_question = current_prompt

                if likely_context_dependent_followup(
                    current_prompt,
                    prior_messages
                ):
                    standalone_question = (
                        resolve_conversational_question(
                            current_prompt,
                            prior_messages
                        )
                    )

                st.session_state[
                    "kh_messages"
                ][-1][
                    "standalone_question"
                ] = standalone_question

                with st.chat_message("user"):
                    st.markdown(current_prompt)

                with st.chat_message("assistant"):
                    with st.status(
                        "Searching and analysing evidence...",
                        expanded=True
                    ) as search_status:

                        st.write("Planning research and selecting sources...")
                        st.write("Retrieving documents and structured data...")
                        st.write("Cross-checking evidence and preparing the answer...")

                        try:

                            result = generate_grounded_answer(
                                standalone_question,
                                depth=active_thread["depth"],
                                response_language=answer_language(current_prompt),
                            )

                            st.session_state[
                                "kh_messages"
                            ].append(
                                {
                                    "role": "assistant",
                                    "content": result["answer"],
                                    "analysis_mode": active_thread["depth"],
                                    "result": result
                                }
                            )

                            search_status.update(
                                label="Analysis complete",
                                state="complete",
                                expanded=False
                            )

                        except Exception as exc:

                            st.session_state["kh_last_error_debug"] = {
                                "type": type(exc).__name__,
                                "frames": [frame.name for frame in traceback.extract_tb(exc.__traceback__)[-6:]],
                            }

                            search_status.update(
                                label="Analysis failed",
                                state="error",
                                expanded=True
                            )

                            st.session_state[
                                "kh_messages"
                            ].append(
                                {
                                    "role": "assistant",
                                    "content": (
                                        "I could not complete this analysis. "
                                        "Please try again later."
                                    ),
                                    "analysis_mode": active_thread["depth"],
                                    "result": None
                                }
                            )

            if research_store:
                try:
                    sync_private_thread(st.session_state["kh_active_thread"])
                except ResearchStoreError:
                    st.session_state["mkh_user_error"] = (
                        "This exchange has not been saved. Use Retry saving when storage is available.")
            st.rerun()
