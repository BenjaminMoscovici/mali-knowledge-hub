
import os
import re
import unicodedata
import importlib.util
from pathlib import Path
from collections import defaultdict

import streamlit as st

from supabase import create_client
from openai import OpenAI


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
        return os.environ[name]


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_SECRET_KEY = get_secret("SUPABASE_SECRET_KEY")
OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
HDX_HAPI_APP_IDENTIFIER = get_secret(
    "HDX_HAPI_APP_IDENTIFIER"
)


supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

openai_client = OpenAI(
    api_key=OPENAI_API_KEY
)


# ============================================================
# OPERATIONAL RUNTIME
# ============================================================

RUNTIME_BUCKET = "knowledge-hub-runtime"
RUNTIME_STORAGE_PATH = "knowledge_hub_runtime_v0_3.py"

runtime_local_path = Path(
    "/tmp/knowledge_hub_runtime_v0_3.py"
)

runtime_bytes = (
    supabase
    .storage
    .from_(RUNTIME_BUCKET)
    .download(RUNTIME_STORAGE_PATH)
)

runtime_local_path.write_bytes(
    runtime_bytes
)

spec = importlib.util.spec_from_file_location(
    "knowledge_hub_runtime",
    runtime_local_path
)

knowledge_hub_runtime = (
    importlib.util.module_from_spec(spec)
)

spec.loader.exec_module(
    knowledge_hub_runtime
)

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
        columns="region,cercle",
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
        "cercles": cercles
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


def resolve_geography(question):

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

    for region in region_matches:

        r = normalize_text(region)

        if (
            f"region de {r}" in q
            or f"region du {r}" in q
            or f"region d'{r}" in q
            or f"region {r}" in q
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


def plan_sources(
    question,
    geography
):

    use_hapi = contains_any_keyword(
        question,
        HUMANITARIAN_KEYWORDS
    )

    use_fongim = contains_any_keyword(
        question,
        FONGIM_KEYWORDS
    )

    return {
        "documents": True,
        "hapi": use_hapi,
        "fongim": use_fongim
    }


# ============================================================
# DOCUMENT FAMILY CLASSIFICATION
# ============================================================

def classify_document_family(item):

    title = normalize_text(
        item.get("document_title")
    )

    organization = normalize_text(
        item.get("organization")
    )

    if (
        "besoins humanitaires" in title
        or "plan de reponse" in title
        or "humanitarian" in title
        or "ocha" in organization
    ):

        return (
            "Humanitarian Response Plan / HNRP"
        )

    return "Government strategies"


# ============================================================
# DOCUMENT EVIDENCE
# ============================================================

@st.cache_data(ttl=3600)
def get_document_groups():
    """
    Resolve document families dynamically from the document registry.

    The HNRP is identified from existing document metadata.
    Every other document in the current corpus belongs to the
    government/development family.
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

        document_type = normalize_text(
            document.get("document_type")
        )

        title = normalize_text(
            document.get("title")
        )

        organization = normalize_text(
            document.get("organization")
        )

        is_hnrp = (
            document_type
            == normalize_text(
                "Humanitarian Needs and Response Plan"
            )
            or "besoins humanitaires" in title
            or "plan de reponse" in title
            or "humanitarian needs" in title
            or (
                "humanitarian" in title
                and "ocha" in organization
            )
        )

        if is_hnrp:
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
            hnrp_document_ids
    }


def build_document_evidence(
    question,
    government_count=10,
    hnrp_count=10
):
    """
    Retrieve government/development evidence and HNRP evidence
    as two independently filtered vector searches.

    Filtering happens inside the Supabase match_chunks RPC before
    vector ranking, so one document family cannot crowd out the other.
    """

    document_groups = get_document_groups()

    government_document_ids = (
        document_groups["government"]
    )

    hnrp_document_ids = (
        document_groups["hnrp"]
    )


    # --------------------------------------------------------
    # 1. GOVERNMENT / DEVELOPMENT STRATEGIES
    # --------------------------------------------------------

    government_results = []

    if government_document_ids:

        government_query = f"""
{question}

Retrieve evidence specifically about Mali's national development
strategy, long-term policy priorities, government objectives,
Vision Mali 2063, SNEDD 2024-2033, structural projects and
development planning.

Focus on the government/development evidence that is most relevant
to the user's question.
"""

        government_results = search_knowledge_base(
            government_query,
            match_count=government_count,
            filter_document_ids=government_document_ids
        )


    # --------------------------------------------------------
    # 2. HUMANITARIAN RESPONSE PLAN / HNRP
    # --------------------------------------------------------

    hnrp_results = []

    if hnrp_document_ids:

        hnrp_query = f"""
{question}

Retrieve evidence specifically from Mali's humanitarian needs
and response planning documents, including humanitarian needs,
response priorities, humanitarian objectives and HNRP 2026.

Focus on the humanitarian planning evidence that is most relevant
to the user's question.
"""

        hnrp_results = search_knowledge_base(
            hnrp_query,
            match_count=hnrp_count,
            filter_document_ids=hnrp_document_ids
        )


    # --------------------------------------------------------
    # 3. COMBINE + DEDUPLICATE
    # --------------------------------------------------------

    combined = (
        government_results
        + hnrp_results
    )

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

        seen.add(
            dedupe_key
        )

        evidence.append({
            "source_type":
                "knowledge_base_document",

            "source_family":
                classify_document_family(
                    result
                ),

            "document_id":
                result.get(
                    "document_id"
                ),

            "document_title":
                result.get(
                    "document_title"
                ),

            "document_type":
                result.get(
                    "document_type"
                ),

            "organization":
                result.get(
                    "organization"
                ),

            "version":
                result.get(
                    "version"
                ),

            "page":
                result.get(
                    "page_number"
                ),

            "section":
                result.get(
                    "section_title"
                ),

            "similarity":
                result.get(
                    "similarity"
                ),

            "content":
                result.get(
                    "content"
                )
        })

    return evidence


# ============================================================
# HAPI REDUCER
# ============================================================

def reduce_hapi_humanitarian_evidence(
    evidence_items,
    max_sector_examples=6
):

    if not evidence_items:
        return []

    total_rows = [
        item
        for item in evidence_items
        if normalize_text(
            item.get(
                "population_category"
            )
        ) == "total"
    ]

    if not total_rows:
        return evidence_items[:30]

    intersectoral = [
        item
        for item in total_rows
        if item.get(
            "sector_name"
        ) == "Intersectoral"
    ]

    intersectoral = sorted(
        intersectoral,
        key=lambda x: (
            x.get("admin1_name") or "",
            x.get("admin2_name") or ""
        )
    )

    sector_rows = [
        item
        for item in total_rows
        if item.get(
            "sector_name"
        ) != "Intersectoral"
    ]

    sector_rows = sorted(
        sector_rows,
        key=lambda x:
            x.get("value") or 0,
        reverse=True
    )

    sector_examples = []
    used_sectors = set()

    for item in sector_rows:

        sector = item.get(
            "sector_name"
        )

        if sector not in used_sectors:

            sector_examples.append(
                item
            )

            used_sectors.add(
                sector
            )

        if (
            len(sector_examples)
            >= max_sector_examples
        ):
            break

    return (
        intersectoral
        + sector_examples
    )


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
                item.get("passage"),

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


def research_fongim(
    geography
):

    location_filters = {
        "is_present_in_source": True
    }

    if geography.get("region"):

        location_filters[
            "region"
        ] = geography["region"]

    if geography.get("cercle"):

        location_filters[
            "cercle"
        ] = geography["cercle"]

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
        row.get(
            "fongim_project_id"
        )
        for row in locations
        if row.get(
            "fongim_project_id"
        ) is not None
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
        row.get(
            "fongim_organization_id"
        )
        for row in project_orgs
        if row.get(
            "fongim_organization_id"
        ) is not None
    })

    organizations = []

    if organization_ids:

        response = (
            supabase
            .table(
                "fongim_organizations"
            )
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

        organizations = (
            response.data or []
        )

    org_name_by_id = {
        row.get(
            "fongim_organization_id"
        ):
        row.get(
            "organization_name"
        )
        for row in organizations
    }


    # --------------------------------------------------------
    # SECTOR COUNTS
    # --------------------------------------------------------

    sector_projects = defaultdict(
        set
    )

    for row in sectors:

        sector = (
            row.get("sector")
            or "Unspecified"
        )

        sector_projects[
            sector
        ].add(
            row.get(
                "fongim_project_id"
            )
        )

    top_sectors = sorted(
        (
            (
                sector,
                len(ids)
            )
            for sector, ids
            in sector_projects.items()
        ),
        key=lambda x: x[1],
        reverse=True
    )


    # --------------------------------------------------------
    # CERCLE COUNTS
    # --------------------------------------------------------

    circle_projects = defaultdict(
        set
    )

    for row in locations:

        cercle = row.get(
            "cercle"
        )

        if cercle:

            circle_projects[
                cercle
            ].add(
                row.get(
                    "fongim_project_id"
                )
            )

    top_cercles = sorted(
        (
            (
                cercle,
                len(ids)
            )
            for cercle, ids
            in circle_projects.items()
        ),
        key=lambda x: x[1],
        reverse=True
    )


    # --------------------------------------------------------
    # ORGANIZATION COUNTS
    # --------------------------------------------------------

    org_projects = defaultdict(
        set
    )

    for row in project_orgs:

        org_id = row.get(
            "fongim_organization_id"
        )

        org_name = (
            org_name_by_id.get(
                org_id
            )
            or str(org_id)
        )

        org_projects[
            org_name
        ].add(
            row.get(
                "fongim_project_id"
            )
        )

    top_orgs = sorted(
        (
            (
                org,
                len(ids)
            )
            for org, ids
            in org_projects.items()
        ),
        key=lambda x: x[1],
        reverse=True
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
            str(
                row.get(
                    "last_synced_at"
                )
            )
            for row in projects
            if row.get(
                "last_synced_at"
            )
        ],
        default=None
    )


    # --------------------------------------------------------
    # BUILD STRUCTURED EVIDENCE
    # --------------------------------------------------------

    evidence = []


    evidence.append({
        "source_type":
            "fongim_structured",

        "source_family":
            "FONGIM intervention data",

        "document_title":
            "FONGIM operational project data",

        "document_type":
            "structured_operational_data",

        "organization":
            "FONGIM",

        "version":
            None,

        "page":
            None,

        "section":
            geographic_scope,

        "content": (
            f"FONGIM records "
            f"{len(project_ids)} unique projects "
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
            for sector, count
            in top_sectors[:10]
        )

        evidence.append({
            "source_type":
                "fongim_structured",

            "source_family":
                "FONGIM intervention data",

            "document_title":
                "FONGIM operational project data",

            "document_type":
                "structured_operational_data",

            "organization":
                "FONGIM",

            "version":
                None,

            "page":
                None,

            "section":
                "Sector profile",

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
            for cercle, count
            in top_cercles[:10]
        )

        evidence.append({
            "source_type":
                "fongim_structured",

            "source_family":
                "FONGIM intervention data",

            "document_title":
                "FONGIM operational project data",

            "document_type":
                "structured_operational_data",

            "organization":
                "FONGIM",

            "version":
                None,

            "page":
                None,

            "section":
                "Recorded geographic presence",

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
            for org, count
            in top_orgs[:10]
        )

        evidence.append({
            "source_type":
                "fongim_structured",

            "source_family":
                "FONGIM intervention data",

            "document_title":
                "FONGIM operational project data",

            "document_type":
                "structured_operational_data",

            "organization":
                "FONGIM",

            "version":
                None,

            "page":
                None,

            "section":
                "Organizations",

            "content": (
                f"Primary organizations associated with "
                f"FONGIM projects in {geographic_scope}: "
                f"{org_text}. "
                f"Counts refer to projects linked to each "
                f"primary organization in the source."
            )
        })


    project_examples = sorted(
        [
            p
            for p in projects
            if p.get(
                "project_name"
            )
        ],
        key=lambda x:
            str(
                x.get(
                    "project_name"
                )
            )
    )[:8]


    if project_examples:

        examples_text = "; ".join(
            (
                f"{p.get('project_name')}"
                + (
                    f" [{p.get('status')}]"
                    if p.get(
                        "status"
                    )
                    else ""
                )
            )
            for p in project_examples
        )

        evidence.append({
            "source_type":
                "fongim_structured",

            "source_family":
                "FONGIM intervention data",

            "document_title":
                "FONGIM operational project data",

            "document_type":
                "structured_operational_data",

            "organization":
                "FONGIM",

            "version":
                None,

            "page":
                None,

            "section":
                "Illustrative project records",

            "content": (
                f"Illustrative project records from the "
                f"selected FONGIM result set: "
                f"{examples_text}. "
                f"These examples are illustrative and are "
                f"not a ranking of projects."
            )
        })


    return {
        "project_count":
            len(project_ids),

        "location_count":
            len(locations),

        "evidence":
            evidence
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
PAGE: {item.get('page')}
SECTION: {item.get('section')}

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

def run_four_source_research(
    question
):

    geography = resolve_geography(
        question
    )

    source_plan = plan_sources(
        question,
        geography
    )

    document_evidence = (
        build_document_evidence(
            question
        )
    )


    hapi_result = {
        "raw_count": 0,
        "evidence": []
    }

    if source_plan["hapi"]:

        hapi_result = (
            build_hapi_evidence(
                geography
            )
        )


    fongim_result = {
        "project_count": 0,
        "location_count": 0,
        "evidence": []
    }

    if source_plan["fongim"]:

        fongim_result = (
            research_fongim(
                geography
            )
        )


    ledger = build_unified_evidence(
        document_evidence,
        hapi_result["evidence"],
        fongim_result["evidence"]
    )


    family_counts = defaultdict(
        int
    )

    for item in ledger:

        family_counts[
            item.get(
                "source_family"
            )
        ] += 1


    return {
        "geography":
            geography,

        "source_plan":
            source_plan,

        "ledger":
            ledger,

        "family_counts":
            dict(
                family_counts
            ),

        "hapi_raw_count":
            hapi_result[
                "raw_count"
            ],

        "fongim_project_count":
            fongim_result[
                "project_count"
            ]
    }


# ============================================================
# ANSWER ENGINE
# ============================================================

def generate_grounded_answer(
    question,
    model="gpt-5-mini"
):

    research = (
        run_four_source_research(
            question
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


    system_prompt = """
You are the analytical engine of the Mali Knowledge Hub.

Your task is to answer the user's question exclusively from the
evidence ledger supplied to you.

The ledger may contain four distinct evidence families:

1. Government strategies
2. Humanitarian Response Plan / HNRP
3. OCHA humanitarian structured data
4. FONGIM intervention data

CORE EPISTEMIC RULE:

Reason across evidence.
Do not reason beyond evidence.

STRICT RULES:

1. Do not use outside knowledge.

2. Do not invent facts, policies, projects, interventions,
   causal relationships, geographic aggregates or citations.

3. Every substantive factual claim must be supported by one or
   more exact evidence IDs, for example [E03] or [E03, E11].

4. You may connect concepts across sources only when the concepts
   themselves are documented in the supplied evidence.

5. Clearly distinguish:
   - source facts
   - analytical synthesis
   - cautious inference
   - evidence limitations

6. Government strategy documents establish stated priorities,
   objectives, diagnoses, targets or scenarios. They do not by
   themselves demonstrate implementation or impact.

7. Humanitarian planning documents and structured humanitarian
   data must not be treated as equivalent evidence if their
   reference periods, definitions or geographic levels differ.

8. NEVER sum Admin2 humanitarian observations to manufacture an
   Admin1 total unless the evidence explicitly provides such an
   aggregate.

9. If the supplied HAPI evidence consists of Admin2 observations,
   describe them as Admin2 observations.

10. Sector examples selected from humanitarian data are examples,
    not a regional ranking unless the evidence explicitly supports
    such a ranking.

11. FONGIM project counts describe recorded project presence.
    They do NOT establish:
    - funding adequacy
    - needs coverage
    - service quality
    - implementation quality
    - effectiveness
    - impact

12. Do not infer a programming gap merely because one FONGIM
    sector has fewer recorded projects than another.

13. A FONGIM project may have multiple sectors and locations.
    Never sum sector or location counts to reconstruct the number
    of projects.

14. If a relationship between humanitarian needs, government
    priorities and operational interventions is only thematic,
    say that it is thematic rather than causal.

15. Scenario passages must never be presented as current facts.

16. If the evidence is insufficient for part of the question,
    state exactly what cannot be established from the supplied
    evidence.

17. Preserve disagreements, different reference periods and
    different levels of aggregation across sources.

18. Prefer concise analytical synthesis over a source-by-source
    dump.

19. Use the language of the user's question.

20. End with a short section titled "Evidence limitations" when
    material limitations affect interpretation.

Do not include a generic bibliography at the end. Citations should
appear directly after the claims they support.
"""


    user_prompt = f"""
QUESTION

{question}


EVIDENCE LEDGER

{evidence_text}


Produce an evidence-grounded analytical answer.
"""


    response = (
        openai_client
        .responses
        .create(
            model=model,
            instructions=system_prompt,
            input=user_prompt
        )
    )


    return {
        "answer":
            response.output_text,

        "evidence":
            ledger,

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
            ]
    }


# ============================================================
# USER INTERFACE
# ============================================================

# ------------------------------------------------------------
# LANDING / SEARCH EXPERIENCE
# ------------------------------------------------------------

st.markdown(
    """
<style>
    .block-container {
        max-width: 1180px;
        padding-top: 5.2rem;
        padding-bottom: 4rem;
    }

    .kh-title {
        font-size: 3.05rem;
        line-height: 1.05;
        font-weight: 800;
        letter-spacing: -0.035em;
        margin: 0 0 0.45rem 0;
        color: #0b2b55;
    }

    .kh-subtitle {
        font-size: 1.08rem;
        line-height: 1.55;
        color: #53657a;
        margin-bottom: 1.8rem;
        max-width: 980px;
    }

    .kh-examples-label {
        font-size: 0.92rem;
        font-weight: 700;
        color: #334a63;
        margin-top: 0.55rem;
        margin-bottom: -0.25rem;
    }

    div[data-testid="stTextArea"] textarea {
        border-radius: 14px;
        border: 1px solid #bfd8ef;
        background: #ffffff;
        font-size: 1rem;
        min-height: 112px;
        box-shadow: 0 3px 14px rgba(32, 100, 160, 0.06);
    }

    div[data-testid="stTextArea"] textarea:focus {
        border-color: #2f8fd5;
        box-shadow: 0 0 0 1px #2f8fd5;
    }

    div[data-testid="stButton"] > button {
        border-radius: 12px;
        font-weight: 650;
    }

    button[kind="primary"] {
        background: #2489d8 !important;
        border-color: #2489d8 !important;
        color: white !important;
        min-height: 3.05rem;
        font-size: 1rem;
    }

    button[kind="primary"]:hover {
        background: #1678c6 !important;
        border-color: #1678c6 !important;
    }

    .kh-example-card {
        border: 1px solid #d9e6f2;
        border-radius: 14px;
        padding: 1rem 1rem 0.9rem 1rem;
        min-height: 128px;
        background: #fbfdff;
        box-shadow: 0 2px 10px rgba(26, 79, 126, 0.045);
        margin-bottom: 0.45rem;
    }

    .kh-example-kicker {
        font-size: 0.82rem;
        font-weight: 800;
        letter-spacing: 0.025em;
        color: #237dc4;
        margin-bottom: 0.45rem;
    }

    .kh-example-text {
        font-size: 0.96rem;
        line-height: 1.42;
        color: #17334f;
        min-height: 66px;
    }

    .kh-how-copy {
        color: #6b7b8d;
        font-size: 0.92rem;
        margin-top: -0.2rem;
        margin-bottom: 0.3rem;
    }

    .kh-section-spacer {
        height: 0.9rem;
    }
</style>

<div class="kh-title">Mali Knowledge Hub</div>
<div class="kh-subtitle">
AI-powered knowledge and analysis platform for Humanitarian,
Development and Peace stakeholders in Mali
</div>
""",
    unsafe_allow_html=True
)


if "knowledge_hub_question" not in st.session_state:
    st.session_state["knowledge_hub_question"] = ""


def set_example_question(example_question):
    st.session_state["knowledge_hub_question"] = example_question


question = st.text_area(
    "Question",
    key="knowledge_hub_question",
    label_visibility="collapsed",
    placeholder="Type your question here...",
    height=112
)


ask = st.button(
    "Analyse evidence",
    type="primary",
    use_container_width=True
)


st.markdown(
    '<div class="kh-examples-label">Try one of these example questions:</div>',
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

    st.button(
        "Use this question →",
        key="example_search",
        use_container_width=True,
        on_click=set_example_question,
        args=(
            "What are the Government's priorities for local "
            "development in Kayes?",
        )
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

    st.button(
        "Use this question →",
        key="example_compare",
        use_container_width=True,
        on_click=set_example_question,
        args=(
            "In Mopti, how do humanitarian needs compare with "
            "current NGO interventions?",
        )
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

    st.button(
        "Use this question →",
        key="example_plan",
        use_container_width=True,
        on_click=set_example_question,
        args=(
            "Where are the main gaps and opportunities for stronger "
            "Humanitarian-Development-Peace coordination in Gao?",
        )
    )


st.markdown(
    '<div class="kh-section-spacer"></div>',
    unsafe_allow_html=True
)


# ------------------------------------------------------------
# HOW THE HUB WORKS — PHASE 1 PLACEHOLDER
# ------------------------------------------------------------

st.markdown(
    '<div class="kh-how-copy">From your question to an evidence-based answer — in 6 steps</div>',
    unsafe_allow_html=True
)

with st.expander(
    "How does the Knowledge Hub work?"
):

    st.markdown(
        """
The Hub first determines which evidence sources are relevant to the
question. It then retrieves document passages and, where relevant,
queries structured humanitarian and intervention data.

Government framework evidence and humanitarian planning evidence are
retrieved separately so that one document family cannot crowd out
the other in broad cross-source questions.

The language model receives only the retrieved evidence. It may
connect concepts documented across sources, but it is instructed
not to introduce substantive facts or causal claims that are absent
from the evidence.

**Core rule:** The AI interprets retrieved evidence; it is not itself
the source of truth.
"""
    )


# ------------------------------------------------------------
# ALREADY AVAILABLE SOURCES — PHASE 1
# ------------------------------------------------------------

st.subheader(
    "Already Available Sources"
)


source_col1, source_col2, source_col3, source_col4 = st.columns(
    4,
    gap="medium"
)


with source_col1:

    st.markdown(
        "**Government Framework Documents**"
    )

    st.caption(
        "National, regional, local and sectoral "
        "strategies and plans"
    )


with source_col2:

    st.markdown(
        "**Humanitarian Needs Assessment**"
    )

    st.caption(
        "Humanitarian needs and response "
        "planning documents"
    )


with source_col3:

    st.markdown(
        "**OCHA Database**"
    )

    st.caption(
        "Live structured humanitarian needs "
        "data via HDX HAPI"
    )


with source_col4:

    st.markdown(
        "**International NGO Activities**"
    )

    st.caption(
        "Structured project information "
        "through the FONGIM database"
    )


st.divider()


# ------------------------------------------------------------
# ANSWER
# ------------------------------------------------------------

if ask and question.strip():

    with st.spinner(
        "Retrieving and analysing evidence..."
    ):

        try:

            result = (
                generate_grounded_answer(
                    question.strip()
                )
            )


            geography = result[
                "geography"
            ]


            if geography.get(
                "assumption"
            ):

                st.info(
                    geography[
                        "assumption"
                    ]
                )


            st.subheader(
                "Analysis"
            )

            st.markdown(
                result[
                    "answer"
                ]
            )


            st.divider()


            # ------------------------------------------------
            # SOURCES USED
            # ------------------------------------------------

            st.subheader(
                "Sources used for this analysis"
            )


            family_counts = result[
                "family_counts"
            ]


            source_labels = [
                "Government strategies",
                "Humanitarian Response Plan / HNRP",
                "OCHA humanitarian data",
                "FONGIM intervention data"
            ]


            for family in source_labels:

                count = family_counts.get(
                    family,
                    0
                )

                if count:

                    st.markdown(
                        f"**✓ {family}** "
                        f"— {count} evidence items"
                    )


            if result[
                "hapi_raw_count"
            ]:

                st.caption(
                    "OCHA structured data were reduced from "
                    f"{result['hapi_raw_count']} source records "
                    "to a smaller evidence set while preserving "
                    "the documented geographic structure."
                )


            if result[
                "fongim_project_count"
            ]:

                st.caption(
                    "FONGIM analysis covered "
                    f"{result['fongim_project_count']} unique "
                    "projects matching the selected geographic scope."
                )


            # ------------------------------------------------
            # EVIDENCE LEDGER
            # ------------------------------------------------

            with st.expander(
                "Inspect evidence"
            ):

                for item in result[
                    "evidence"
                ]:

                    page = (
                        f" · p. {item['page']}"
                        if item.get(
                            "page"
                        ) is not None
                        else ""
                    )


                    label = (
                        f"{item['evidence_id']} — "
                        f"{item.get('source_family')}"
                        f"{page}"
                    )


                    with st.expander(
                        label
                    ):

                        if item.get(
                            "document_title"
                        ):

                            st.markdown(
                                "**Source:** "
                                f"{item['document_title']}"
                            )


                        if item.get(
                            "organization"
                        ):

                            st.markdown(
                                "**Organization:** "
                                f"{item['organization']}"
                            )


                        if item.get(
                            "section"
                        ):

                            st.markdown(
                                "**Section / dimension:** "
                                f"{item['section']}"
                            )


                        if item.get(
                            "version"
                        ):

                            st.markdown(
                                "**Version:** "
                                f"{item['version']}"
                            )


                        st.markdown(
                            "**Evidence:**"
                        )


                        st.write(
                            item.get(
                                "content"
                            )
                        )


        except Exception as exc:

            st.error(
                f"Knowledge Hub error: {exc}"
            )


elif ask:

    st.warning(
        "Please enter a question."
    )

