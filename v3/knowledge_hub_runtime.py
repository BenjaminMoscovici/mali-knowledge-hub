
# ============================================================
# MALI KNOWLEDGE HUB — OPERATIONAL RUNTIME v0.3
# ============================================================

import hashlib
import os
from provider_reads import execute_read
import time
import uuid
from datetime import datetime, timezone

import pandas as pd
import requests
from metering import QUERY_ID
from source_sync_guards import paginated_hapi, validate_fongim_refresh


# ============================================================
# Runtime clients
# ============================================================

supabase = None
openai_client = None
hdx_hapi_app_identifier = None


def configure_runtime(
    supabase_client,
    openai_client_instance,
    hdx_hapi_app_identifier_instance=None
):
    """
    Attach initialized Supabase, OpenAI and HDX HAPI
    configuration to the runtime.

    The clients and configuration are created by:
    00 — START MALI KNOWLEDGE HUB
    """

    global supabase
    global openai_client
    global hdx_hapi_app_identifier

    supabase = supabase_client
    openai_client = openai_client_instance
    hdx_hapi_app_identifier = hdx_hapi_app_identifier_instance


def _require_supabase():
    if supabase is None:
        raise RuntimeError(
            "Supabase client is not configured. "
            "Call configure_runtime(...) first."
        )


def _require_openai():
    if openai_client is None:
        raise RuntimeError(
            "OpenAI client is not configured. "
            "Call configure_runtime(...) first."
        )


# ============================================================
# Retrieval Engine
# ============================================================

def search_knowledge_base(
    question,
    match_count=12,
    filter_document_ids=None,
    similarity_threshold=None,
    document_metadata=None
):
    """
    Search the Knowledge Hub document corpus.

    Optional document filtering allows retrieval to be restricted
    to a defined subset of documents before vector ranking.

    Returns ranked chunks enriched with document metadata
    so provenance is preserved throughout the pipeline.
    """

    _require_supabase()
    _require_openai()


    # --------------------------------------------------------
    # 1. Embed the question
    # --------------------------------------------------------

    embedding_response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=question
    )

    query_embedding = embedding_response.data[0].embedding


    # --------------------------------------------------------
    # 2. Vector search in Supabase
    # --------------------------------------------------------

    response = execute_read(supabase.rpc(
        "match_chunks",
        {
            "query_embedding": query_embedding,
            "match_count": match_count,
            "filter_document_ids": filter_document_ids
        }
    ), "search_knowledge_base")

    raw_results = response.data or []


    # --------------------------------------------------------
    # 3. Optional similarity threshold
    # --------------------------------------------------------

    if similarity_threshold is not None:

        raw_results = [
            r
            for r in raw_results
            if (
                r.get("similarity") is not None
                and r.get("similarity") >= similarity_threshold
            )
        ]


    # --------------------------------------------------------
    # 4. Load document metadata once
    # --------------------------------------------------------

    document_ids = list({
        r.get("document_id")
        for r in raw_results
        if r.get("document_id")
    })

    # The routed document registry has already been read in this request.
    # Reuse its complete metadata snapshot; fall back for any missing entry.
    required_fields = {'id','title','organization','publication_date','valid_from',
                       'valid_until','document_type','language','geographic_scope','status','version'}
    documents_by_id = {d['id']: dict(d) for d in (document_metadata or [])
                       if required_fields <= d.keys()}
    missing_document_ids = [did for did in document_ids if did not in documents_by_id]

    if missing_document_ids:

        docs_response = (
            execute_read(supabase
            .table("documents")
            .select(
                "id,title,organization,publication_date,"
                "valid_from,valid_until,document_type,"
                "language,geographic_scope,status,version"
            )
            .in_("id", missing_document_ids), "search_knowledge_base")
        )

        documents_by_id.update({
            d["id"]: d
            for d in docs_response.data
        })


    # --------------------------------------------------------
    # 5. Enrich every chunk with provenance
    # --------------------------------------------------------

    results = []

    for r in raw_results:

        doc = documents_by_id.get(
            r.get("document_id"),
            {}
        )

        results.append({
            **r,

            "document_title": doc.get("title"),
            "organization": doc.get("organization"),
            "publication_date": doc.get("publication_date"),
            "valid_from": doc.get("valid_from"),
            "valid_until": doc.get("valid_until"),
            "document_type": doc.get("document_type"),
            "language": doc.get("language"),
            "geographic_scope": doc.get("geographic_scope"),
            "document_status": doc.get("status"),
            "version": doc.get("version")
        })

    return results

# ============================================================
# OCHA / HDX HAPI Connector
# ============================================================

HAPI_POPULATION_STATUS_LABELS = {
    "INN": "People in need",
    "TGT": "People targeted",
    "all": "All / source aggregate"
}

HAPI_RESOURCE_METADATA_CACHE = {}


def _require_hapi():
    if not hdx_hapi_app_identifier:
        raise RuntimeError(
            "HDX HAPI is not configured. "
            "Pass HDX_HAPI_APP_IDENTIFIER to configure_runtime(...)."
        )


def hapi_get(
    endpoint,
    params=None,
    limit=1000,
    offset=0,
    timeout=30
):
    _require_hapi()

    if params is None:
        params = {}

    query_params = {
        **params,
        "limit": limit,
        "offset": offset,
        "output_format": "json"
    }

    headers = {
        "X-HDX-HAPI-APP-IDENTIFIER": hdx_hapi_app_identifier
    }

    url = (
        "https://hapi.humdata.org/api/v2/"
        f"{endpoint.lstrip('/')}"
    )

    started = time.perf_counter()
    try:
        response = requests.get(
            url,
            params=query_params,
            headers=headers,
            timeout=timeout
        )
    finally:
        if hasattr(openai_client, "add_external"):
            openai_client.add_external(QUERY_ID.get(), {
                "provider": "HDX HAPI", "endpoint": endpoint,
                "seconds": round(time.perf_counter() - started, 3),
            })

    response.raise_for_status()

    return response.json()


def _stable_hapi_evidence_id(row, endpoint):
    import json

    identity = {
        "endpoint": endpoint,
        "resource_hdx_id": row.get("resource_hdx_id"),
        "location_code": row.get("location_code"),
        "admin1_code": row.get("admin1_code"),
        "admin2_code": row.get("admin2_code"),
        "sector_code": row.get("sector_code"),
        "category": row.get("category"),
        "population_status": row.get("population_status"),
        "population": row.get("population"),
        "reference_period_start": row.get("reference_period_start"),
        "reference_period_end": row.get("reference_period_end")
    }

    raw = json.dumps(
        identity,
        sort_keys=True,
        ensure_ascii=False
    ).encode("utf-8")

    digest = hashlib.sha256(raw).hexdigest()[:12]

    return f"HAPI-{digest}"


def normalize_humanitarian_need_record(row):
    endpoint = "affected-people/humanitarian-needs"

    status_raw = row.get("population_status")

    status_label = HAPI_POPULATION_STATUS_LABELS.get(
        status_raw,
        status_raw
    )

    admin1 = row.get("admin1_name")
    admin2 = row.get("admin2_name")

    if admin2:
        location_text = f"{admin2}, {admin1}, Mali"
    elif admin1:
        location_text = f"{admin1}, Mali"
    else:
        location_text = "Mali"

    sector = row.get("sector_name") or "Unspecified sector"
    category = (
        row.get("category")
        or "Unspecified population category"
    )
    population = row.get("population")

    period_start = row.get("reference_period_start")
    period_end = row.get("reference_period_end")

    if isinstance(population, (int, float)):
        passage = (
            f"{status_label}: {population:,} people; "
            f"sector: {sector}; "
            f"population category: {category}; "
            f"location: {location_text}; "
            f"reference period: "
            f"{period_start} to {period_end}."
        )
    else:
        passage = (
            f"{status_label}; "
            f"sector: {sector}; "
            f"population category: {category}; "
            f"location: {location_text}; "
            f"reference period: "
            f"{period_start} to {period_end}."
        )

    return {
        "evidence_id": _stable_hapi_evidence_id(
            row,
            endpoint
        ),
        "source_type": "hdx_hapi",
        "document_id": None,
        "document_title":
            "HDX HAPI — Humanitarian Needs",
        "document_type":
            "structured_humanitarian_data",
        "organization": "OCHA / HDX",
        "publication_date": None,
        "version": None,
        "page": None,
        "section": sector,
        "chunk_id": None,
        "similarity": None,
        "retrieved_for": None,
        "passage": passage,
        "evidence_type": "structured_data",
        "supports": None,
        "source_endpoint": endpoint,
        "resource_hdx_id":
            row.get("resource_hdx_id"),
        "retrieved_at":
            datetime.now(timezone.utc).isoformat(),
        "reference_period_start": period_start,
        "reference_period_end": period_end,
        "location_code": row.get("location_code"),
        "location_name": row.get("location_name"),
        "admin_level": row.get("admin_level"),
        "admin1_code": row.get("admin1_code"),
        "admin1_name": admin1,
        "admin2_code": row.get("admin2_code"),
        "admin2_name": admin2,
        "sector_code": row.get("sector_code"),
        "sector_name": sector,
        "population_category": category,
        "population_status": status_raw,
        "population_status_label": status_label,
        "value": population,
        "unit": "people",
        "raw_record": row
    }


def normalize_humanitarian_needs(rows):
    return [
        normalize_humanitarian_need_record(row)
        for row in rows
    ]


def get_hapi_resource_metadata(resource_hdx_id):
    result = hapi_get(
        "metadata/resource",
        params={
            "resource_hdx_id": resource_hdx_id
        },
        limit=100
    )

    return result.get("data", [])


def enrich_hapi_evidence(
    evidence_item,
    resource_metadata
):
    if not resource_metadata:
        return evidence_item

    meta = resource_metadata[0]

    return {
        **evidence_item,
        "source_platform": "HDX HAPI",
        "resource_name": meta.get("name"),
        "resource_format": meta.get("format"),
        "resource_update_date":
            meta.get("update_date"),
        "resource_download_url":
            meta.get("download_url"),
        "resource_hdx_link": meta.get("hdx_link"),
        "dataset_hdx_id":
            meta.get("dataset_hdx_id"),
        "dataset_title":
            meta.get("dataset_hdx_title"),
        "dataset_hdx_link":
            meta.get("dataset_hdx_link"),
        "provider_name":
            meta.get(
                "dataset_hdx_provider_name"
            ),
        "provider_stub":
            meta.get(
                "dataset_hdx_provider_stub"
            ),
        "provider_hdx_link":
            meta.get("provider_hdx_link"),
        "hapi_updated_date":
            meta.get("hapi_updated_date")
    }


def get_cached_resource_metadata(resource_hdx_id):
    if not resource_hdx_id:
        return []

    if (
        resource_hdx_id
        in HAPI_RESOURCE_METADATA_CACHE
    ):
        return HAPI_RESOURCE_METADATA_CACHE[
            resource_hdx_id
        ]

    metadata = get_hapi_resource_metadata(
        resource_hdx_id
    )

    HAPI_RESOURCE_METADATA_CACHE[
        resource_hdx_id
    ] = metadata

    return metadata


def enrich_hapi_evidence_batch(evidence_items):
    enriched_items = []

    resource_ids = {
        item.get("resource_hdx_id")
        for item in evidence_items
        if item.get("resource_hdx_id")
    }

    for resource_id in resource_ids:
        get_cached_resource_metadata(resource_id)

    for item in evidence_items:
        resource_id = item.get(
            "resource_hdx_id"
        )

        metadata = (
            HAPI_RESOURCE_METADATA_CACHE.get(
                resource_id,
                []
            )
            if resource_id
            else []
        )

        enriched_items.append(
            enrich_hapi_evidence(
                item,
                metadata
            )
        )

    return enriched_items


def research_humanitarian_needs(
    admin1_name=None,
    admin2_name=None,
    sector_name=None,
    population_status="INN",
    latest_only=True,
    limit=10000
):
    params = {
        "location_code": "MLI"
    }

    if admin1_name:
        params["admin1_name"] = admin1_name

    if admin2_name:
        params["admin2_name"] = admin2_name

    if sector_name:
        params["sector_name"] = sector_name

    if population_status:
        params[
            "population_status"
        ] = population_status

    rows = paginated_hapi(hapi_get, "affected-people/humanitarian-needs",
                          params, max_records=limit)

    if not rows:
        return []

    if latest_only:
        available_periods = [
            row.get("reference_period_end")
            for row in rows
            if row.get("reference_period_end")
        ]

        if available_periods:
            latest_period_end = max(
                available_periods
            )

            rows = [
                row
                for row in rows
                if row.get(
                    "reference_period_end"
                ) == latest_period_end
            ]

    evidence = normalize_humanitarian_needs(
        rows
    )

    evidence = enrich_hapi_evidence_batch(
        evidence
    )

    return evidence

# ============================================================
# FONGIM Connector — Configuration
# ============================================================

FONGIM_SOURCE_URL = "https://www.fongim.org/carte-interactive"

FONGIM_QUERYDATA_URL = (
    "https://wabi-south-africa-north-a-primary-api.analysis.windows.net/"
    "public/reports/querydata?synchronous=true"
)

FONGIM_MODEL_ID = 2218134

FONGIM_HEADERS = {
    "Content-Type": "application/json",
    "X-PowerBI-ResourceKey": os.environ.get("FONGIM_POWERBI_RESOURCE_KEY", "")
}


def build_fongim_payload(
    entity,
    source_alias,
    fields,
    count=10000
):
    """
    Build a standard FONGIM Power BI query payload.

    fields:
        list of (source_field, output_name)
    """

    selects = []

    for source_field, output_name in fields:

        selects.append({
            "Column": {
                "Expression": {
                    "SourceRef": {
                        "Source": source_alias
                    }
                },
                "Property": source_field
            },
            "Name": output_name
        })

    return {
        "version": "1.0.0",
        "queries": [
            {
                "Query": {
                    "Commands": [
                        {
                            "SemanticQueryDataShapeCommand": {
                                "Query": {
                                    "Version": 2,
                                    "From": [
                                        {
                                            "Name": source_alias,
                                            "Entity": entity,
                                            "Type": 0
                                        }
                                    ],
                                    "Select": selects
                                },
                                "Binding": {
                                    "Primary": {
                                        "Groupings": [
                                            {
                                                "Projections":
                                                    list(
                                                        range(
                                                            len(fields)
                                                        )
                                                    )
                                            }
                                        ]
                                    },
                                    "DataReduction": {
                                        "DataVolume": 6,
                                        "Primary": {
                                            "Window": {
                                                "Count": count
                                            }
                                        }
                                    },
                                    "Version": 1
                                },
                                "ExecutionMetricsKind": 1
                            }
                        }
                    ]
                },
                "QueryId": ""
            }
        ],
        "cancelQueries": [],
        "modelId": FONGIM_MODEL_ID
    }


FONGIM_PROJECT_FIELDS = [
    ("_index", "fongim_project_id"),
    ("Quel est le nom du projet ?", "project_name"),
    ("Date de début de la mise en œuvre", "start_date"),
    ("Date de fin de la mise en œuvre", "end_date"),
    ("Statut", "status"),
    ("Comment qualifiez vous votre projet ?", "project_type"),
    ("Le nombre total de bénéficiares du projet", "beneficiaries"),
    ("Quel est le bailleur ?", "donor"),
    ("Quel le montant du financement", "funding_amount_raw"),
    (
        "Quel(s) est/sont le(s) partenaire(s) du projet",
        "partners_raw"
    ),
    (
        "travaillez-vous avec des partenaires dans ce projet",
        "has_partners"
    )
]

FONGIM_LOCATION_FIELDS = [
    ("ID_projet", "fongim_project_id"),
    ("ID_zone", "fongim_zone_id"),
    ("Région", "region"),
    ("Cercle", "cercle"),
    ("Commune", "commune_raw")
]

FONGIM_SECTOR_FIELDS = [
    ("ID_projet", "fongim_project_id"),
    ("Secteurs", "sector"),
    ("Autres", "sector_other_raw")
]

FONGIM_ORGANIZATION_FIELDS = [
    ("id", "fongim_organization_id"),
    ("nom_org", "organization_name")
]

FONGIM_PARTNER_FIELDS = [
    ("ID_projet", "fongim_project_id"),
    ("Partenaire", "partner_name"),
    ("ID_ONG", "fongim_organization_id")
]

FONGIM_FUNDING_FIELDS = [
    ("id", "funding_id"),
    ("nom_org", "organization_name"),
    ("_index", "funding_index"),
    ("Projet ", "project_name_raw"),
    ("Type", "project_type"),
    ("Secteurs", "sector"),
    ("M2024", "funding_2024"),
    ("M2025", "funding_2025")
]


project_master_payload = build_fongim_payload(
    "Projets",
    "p",
    FONGIM_PROJECT_FIELDS,
    count=5000
)

location_payload = build_fongim_payload(
    "Zones",
    "z",
    FONGIM_LOCATION_FIELDS
)

sector_payload = build_fongim_payload(
    "Secteurs",
    "s",
    FONGIM_SECTOR_FIELDS
)

organization_payload = build_fongim_payload(
    "Organisations",
    "o",
    FONGIM_ORGANIZATION_FIELDS
)

partner_payload = build_fongim_payload(
    "Partenaires",
    "pa",
    FONGIM_PARTNER_FIELDS
)

funding_payload = build_fongim_payload(
    "funding",
    "f",
    FONGIM_FUNDING_FIELDS
)


project_org_payload = {
    "version": "1.0.0",
    "queries": [
        {
            "Query": {
                "Commands": [
                    {
                        "SemanticQueryDataShapeCommand": {
                            "Query": {
                                "Version": 2,
                                "From": [
                                    {
                                        "Name": "p",
                                        "Entity": "Projets",
                                        "Type": 0
                                    },
                                    {
                                        "Name": "o",
                                        "Entity": "Organisations",
                                        "Type": 0
                                    }
                                ],
                                "Select": [
                                    {
                                        "Column": {
                                            "Expression": {
                                                "SourceRef": {
                                                    "Source": "p"
                                                }
                                            },
                                            "Property": "_index"
                                        },
                                        "Name": "fongim_project_id"
                                    },
                                    {
                                        "Column": {
                                            "Expression": {
                                                "SourceRef": {
                                                    "Source": "p"
                                                }
                                            },
                                            "Property":
                                                "Quel est le nom du projet ?"
                                        },
                                        "Name": "project_name"
                                    },
                                    {
                                        "Column": {
                                            "Expression": {
                                                "SourceRef": {
                                                    "Source": "o"
                                                }
                                            },
                                            "Property": "id"
                                        },
                                        "Name": "fongim_organization_id"
                                    },
                                    {
                                        "Column": {
                                            "Expression": {
                                                "SourceRef": {
                                                    "Source": "o"
                                                }
                                            },
                                            "Property": "nom_org"
                                        },
                                        "Name": "organization_name"
                                    }
                                ]
                            },
                            "Binding": {
                                "Primary": {
                                    "Groupings": [
                                        {
                                            "Projections": [0, 1, 2, 3]
                                        }
                                    ]
                                },
                                "DataReduction": {
                                    "DataVolume": 6,
                                    "Primary": {
                                        "Window": {
                                            "Count": 5000
                                        }
                                    }
                                },
                                "Version": 1
                            },
                            "ExecutionMetricsKind": 1
                        }
                    }
                ]
            },
            "QueryId": ""
        }
    ],
    "cancelQueries": [],
    "modelId": FONGIM_MODEL_ID
}


# ============================================================
# FONGIM Connector — Power BI Decoder
# ============================================================

def decode_powerbi_rows(response_json):
    """
    Decode the primary Power BI DSR grouping returned by querydata.
    Supports:
    - dictionary encoded strings
    - repeated values via R bitmask
    - Power BI date timestamps
    """

    result = response_json["results"][0]["result"]["data"]

    descriptor = result["descriptor"]["Select"]
    column_names = [item["Name"] for item in descriptor]

    ds = result["dsr"]["DS"][0]
    rows = ds["PH"][0]["DM0"]
    value_dicts = ds.get("ValueDicts", {})

    schema = rows[0].get("S", [])

    column_meta = []

    for i, col in enumerate(schema):
        column_meta.append({
            "name": col.get("N"),
            "type": col.get("T"),
            "dict": col.get("DN")
        })

    decoded_rows = []
    previous = [None] * len(column_names)

    for row in rows:
        values = [None] * len(column_names)

        repeat_mask = row.get("R", 0)
        raw_values = iter(row.get("C", []))

        for i in range(len(column_names)):

            if repeat_mask & (1 << i):
                values[i] = previous[i]
                continue

            try:
                value = next(raw_values)
            except StopIteration:
                value = None

            meta = (
                column_meta[i]
                if i < len(column_meta)
                else {}
            )

            dict_name = meta.get("dict")

            if dict_name and value is not None:
                dictionary = value_dicts.get(
                    dict_name,
                    []
                )

                if (
                    isinstance(value, int)
                    and value < len(dictionary)
                ):
                    value = dictionary[value]

            if (
                meta.get("type") == 7
                and isinstance(value, (int, float))
            ):
                value = datetime.fromtimestamp(
                    value / 1000,
                    tz=timezone.utc
                ).date().isoformat()

            values[i] = value

        decoded_rows.append(values)
        previous = values

    return pd.DataFrame(
        decoded_rows,
        columns=column_names
    )


# ============================================================
# FONGIM Connector — Extract & Validate
# ============================================================

def run_fongim_sync_extract():
    """
    Pull the current FONGIM operational dataset from the public
    Power BI semantic model and return validated relational tables.

    No Supabase writes are performed here.
    """

    sync_started_at = datetime.now(timezone.utc)
    sync_run_id = str(uuid.uuid4())

    print("=" * 70)
    print("FONGIM SYNC EXTRACT")
    print("=" * 70)
    print("Sync run:", sync_run_id)
    print("Started:", sync_started_at.isoformat())

    def execute_payload(payload, label):

        response = requests.post(
            FONGIM_QUERYDATA_URL,
            headers=FONGIM_HEADERS,
            json=payload,
            timeout=30
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"{label} failed with HTTP "
                f"{response.status_code}: "
                f"{response.text[:500]}"
            )

        df = decode_powerbi_rows(
            response.json()
        )

        print(
            f"✓ {label}: {len(df)} rows"
        )

        return df

    projects = execute_payload(
        project_master_payload,
        "Projects"
    )

    locations = execute_payload(
        location_payload,
        "Locations"
    )

    sectors = execute_payload(
        sector_payload,
        "Sectors"
    )

    organizations = execute_payload(
        organization_payload,
        "Organizations"
    )

    project_organizations = execute_payload(
        project_org_payload,
        "Project organizations"
    )

    partners = execute_payload(
        partner_payload,
        "Partners"
    )

    funding_raw = execute_payload(
        funding_payload,
        "Funding"
    )

    project_ids_current = set(
        projects["fongim_project_id"]
    )

    if projects[
        "fongim_project_id"
    ].duplicated().any():
        raise ValueError(
            "FONGIM sync aborted: duplicate "
            "project IDs detected."
        )

    orphan_locations = (
        set(locations["fongim_project_id"])
        - project_ids_current
    )

    orphan_sectors = (
        set(sectors["fongim_project_id"])
        - project_ids_current
    )

    orphan_partners = (
        set(partners["fongim_project_id"])
        - project_ids_current
    )

    orphan_project_orgs = (
        set(
            project_organizations[
                "fongim_project_id"
            ]
        )
        - project_ids_current
    )

    if orphan_locations:
        raise ValueError(
            f"FONGIM sync aborted: "
            f"{len(orphan_locations)} orphan "
            "location project IDs."
        )

    if orphan_sectors:
        raise ValueError(
            f"FONGIM sync aborted: "
            f"{len(orphan_sectors)} orphan "
            "sector project IDs."
        )

    if orphan_partners:
        raise ValueError(
            f"FONGIM sync aborted: "
            f"{len(orphan_partners)} orphan "
            "partner project IDs."
        )

    if orphan_project_orgs:
        raise ValueError(
            f"FONGIM sync aborted: "
            f"{len(orphan_project_orgs)} orphan "
            "project-organization IDs."
        )

    organization_ids_current = set(
        organizations[
            "fongim_organization_id"
        ]
    )

    project_org_ids_current = set(
        project_organizations[
            "fongim_organization_id"
        ]
    )

    partner_org_ids_current = set(
        partners[
            "fongim_organization_id"
        ].dropna()
    )

    unmatched_project_orgs = (
        project_org_ids_current
        - organization_ids_current
    )

    unmatched_partner_orgs = (
        partner_org_ids_current
        - organization_ids_current
    )

    if unmatched_project_orgs:
        raise ValueError(
            f"FONGIM sync aborted: "
            f"{len(unmatched_project_orgs)} "
            "project organization IDs missing "
            "from Organisations."
        )

    if unmatched_partner_orgs:
        raise ValueError(
            f"FONGIM sync aborted: "
            f"{len(unmatched_partner_orgs)} "
            "partner organization IDs missing "
            "from Organisations."
        )

    orgs_per_project = (
        project_organizations
        .groupby(
            "fongim_project_id"
        )["fongim_organization_id"]
        .nunique()
    )

    multi_org_projects = (
        orgs_per_project[
            orgs_per_project > 1
        ]
    )

    if len(multi_org_projects):
        raise ValueError(
            f"FONGIM sync aborted: "
            f"{len(multi_org_projects)} projects "
            "have multiple primary organizations."
        )

    funding = funding_raw.copy()

    funding[
        "funding_index_numeric"
    ] = pd.to_numeric(
        funding["funding_index"],
        errors="coerce"
    )

    project_lookup = projects[
        [
            "fongim_project_id",
            "project_name"
        ]
    ].copy()

    project_lookup[
        "fongim_project_id_numeric"
    ] = pd.to_numeric(
        project_lookup[
            "fongim_project_id"
        ],
        errors="coerce"
    )

    funding = funding.merge(
        project_lookup,
        left_on="funding_index_numeric",
        right_on="fongim_project_id_numeric",
        how="left",
        suffixes=(
            "_funding",
            "_canonical"
        )
    )

    funding["linkage_status"] = (
        funding[
            "fongim_project_id"
        ]
        .notna()
        .map({
            True: "linked_native_id",
            False: "unlinked_native_id"
        })
    )

    funding = funding.drop(
        columns=[
            "fongim_project_id_numeric"
        ]
    )

    sync_finished_at = datetime.now(
        timezone.utc
    )

    metadata = {
        "sync_run_id": sync_run_id,
        "source_system": "FONGIM",
        "source_url": FONGIM_SOURCE_URL,
        "source_model_id": FONGIM_MODEL_ID,
        "sync_started_at":
            sync_started_at.isoformat(),
        "sync_finished_at":
            sync_finished_at.isoformat(),
        "project_count":
            len(projects),
        "location_count":
            len(locations),
        "sector_count":
            len(sectors),
        "organization_count":
            len(organizations),
        "project_organization_count":
            len(project_organizations),
        "partner_count":
            len(partners),
        "funding_row_count":
            len(funding),
        "funding_project_count":
            funding[
                "funding_index"
            ].nunique(),
        "funding_linked_project_count":
            funding.loc[
                funding[
                    "linkage_status"
                ] == "linked_native_id",
                "funding_index"
            ].nunique(),
        "funding_unlinked_project_count":
            funding.loc[
                funding[
                    "linkage_status"
                ] == "unlinked_native_id",
                "funding_index"
            ].nunique(),
    }

    print()
    print("=" * 70)
    print("SYNC VALIDATION COMPLETE")
    print("=" * 70)

    for key, value in metadata.items():
        print(f"{key}: {value}")

    return {
        "metadata":
            metadata,
        "projects":
            projects,
        "locations":
            locations,
        "sectors":
            sectors,
        "organizations":
            organizations,
        "project_organizations":
            project_organizations,
        "partners":
            partners,
        "funding":
            funding
    }


# ============================================================
# FONGIM Connector — Persistence Helpers
# ============================================================

def fongim_db_value(value):
    """
    Convert pandas / numpy values into
    Supabase-safe values.
    """

    if pd.isna(value):
        return None

    if hasattr(value, "item"):
        value = value.item()

    if isinstance(
        value,
        (pd.Timestamp, datetime)
    ):
        return value.isoformat()

    if (
        isinstance(value, float)
        and value.is_integer()
    ):
        return int(value)

    return value


def fongim_stable_key(*values):
    """
    Create deterministic SHA-256 key
    from stable source fields.
    """

    normalized = []

    for value in values:

        value = fongim_db_value(value)

        if value is None:
            normalized.append("")
        else:
            normalized.append(
                str(value).strip()
            )

    raw = "||".join(normalized)

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def fongim_validate_unique(
    records,
    key,
    dataset_name
):

    values = [
        record[key]
        for record in records
    ]

    if any(
        value is None
        for value in values
    ):
        raise ValueError(
            f"{dataset_name}: NULL key "
            f"detected in {key}"
        )

    if len(values) != len(set(values)):
        raise ValueError(
            f"{dataset_name}: duplicate "
            f"{key} detected"
        )


def fongim_upsert_batches(
    table_name,
    records,
    conflict_column,
    batch_size=250
):
    """
    Upsert records in controlled batches.
    """

    _require_supabase()

    written = 0

    for start in range(
        0,
        len(records),
        batch_size
    ):

        batch = records[
            start:start + batch_size
        ]

        (
            supabase
            .table(table_name)
            .upsert(
                batch,
                on_conflict=conflict_column
            )
            .execute()
        )

        written += len(batch)

    return written


def fongim_mark_missing_inactive(
    table_name,
    key_column,
    current_keys,
    sync_time
):
    """
    Mark records no longer present
    in FONGIM as inactive.

    Never deletes historical records.
    """

    _require_supabase()

    existing_keys = set()

    page_size = 1000
    start = 0

    while True:

        result = (
            supabase
            .table(table_name)
            .select(key_column)
            .range(
                start,
                start + page_size - 1
            )
            .execute()
        )

        rows = result.data or []

        for row in rows:
            existing_keys.add(
                row[key_column]
            )

        if len(rows) < page_size:
            break

        start += page_size

    missing_keys = (
        existing_keys
        - set(current_keys)
    )

    for key in missing_keys:

        (
            supabase
            .table(table_name)
            .update({
                "is_present_in_source":
                    False,
                "last_synced_at":
                    sync_time
            })
            .eq(
                key_column,
                key
            )
            .execute()
        )

    return len(missing_keys)


# ============================================================
# FONGIM Connector — Complete Synchronization
# ============================================================

def run_complete_fongim_sync(*, reviewed_shrink_reason=None):

    _require_supabase()

    print("=" * 70)
    print("COMPLETE FONGIM SYNC")
    print("=" * 70)

    print(
        "1/7  Extracting and validating FONGIM..."
    )

    source = run_fongim_sync_extract()

    metadata = source["metadata"]

    sync_run_id = metadata["sync_run_id"]
    sync_time = metadata["sync_finished_at"]

    projects_df = source[
        "projects"
    ].copy()

    organizations_df = source[
        "organizations"
    ].copy()

    project_orgs_df = source[
        "project_organizations"
    ].copy()

    locations_df = source[
        "locations"
    ].copy()

    sectors_df = source[
        "sectors"
    ].copy()

    partners_df = source[
        "partners"
    ].copy()

    funding_df = source[
        "funding"
    ].copy()

    print(
        "     ✓ Source extraction validated"
    )

    print(
        "2/7  Preparing canonical records..."
    )

    project_records = []

    for _, row in projects_df.iterrows():

        project_records.append({
            "fongim_project_id":
                fongim_db_value(
                    row[
                        "fongim_project_id"
                    ]
                ),

            "project_name":
                fongim_db_value(
                    row["project_name"]
                ),

            "start_date":
                fongim_db_value(
                    row["start_date"]
                ),

            "end_date":
                fongim_db_value(
                    row["end_date"]
                ),

            "status":
                fongim_db_value(
                    row["status"]
                ),

            "project_type":
                fongim_db_value(
                    row["project_type"]
                ),

            "beneficiaries":
                fongim_db_value(
                    row["beneficiaries"]
                ),

            "donor":
                fongim_db_value(
                    row["donor"]
                ),

            "funding_amount_raw":
                fongim_db_value(
                    row[
                        "funding_amount_raw"
                    ]
                ),

            "partners_raw":
                fongim_db_value(
                    row["partners_raw"]
                ),

            "has_partners":
                fongim_db_value(
                    row["has_partners"]
                ),

            "last_seen_at":
                sync_time,
            "last_synced_at":
                sync_time,
            "is_present_in_source":
                True,
            "last_seen_sync_id":
                sync_run_id,

            "source_system":
                "FONGIM",
            "source_model_id":
                FONGIM_MODEL_ID
        })

    fongim_validate_unique(
        project_records,
        "fongim_project_id",
        "Projects"
    )

    organization_records = []

    for _, row in organizations_df.iterrows():

        organization_records.append({
            "fongim_organization_id":
                fongim_db_value(
                    row[
                        "fongim_organization_id"
                    ]
                ),

            "organization_name":
                fongim_db_value(
                    row[
                        "organization_name"
                    ]
                ),

            "last_seen_at":
                sync_time,
            "last_synced_at":
                sync_time,
            "is_present_in_source":
                True,
            "last_seen_sync_id":
                sync_run_id,

            "source_system":
                "FONGIM",
            "source_model_id":
                FONGIM_MODEL_ID
        })

    fongim_validate_unique(
        organization_records,
        "fongim_organization_id",
        "Organizations"
    )

    project_organization_records = []

    for _, row in project_orgs_df.iterrows():

        project_organization_records.append({
            "fongim_project_id":
                fongim_db_value(
                    row[
                        "fongim_project_id"
                    ]
                ),

            "fongim_organization_id":
                fongim_db_value(
                    row[
                        "fongim_organization_id"
                    ]
                ),

            "last_seen_at":
                sync_time,
            "last_synced_at":
                sync_time,
            "is_present_in_source":
                True,
            "last_seen_sync_id":
                sync_run_id
        })

    fongim_validate_unique(
        project_organization_records,
        "fongim_project_id",
        "Project organizations"
    )

    location_records = []

    for _, row in locations_df.iterrows():

        project_id = fongim_db_value(
            row["fongim_project_id"]
        )

        zone_id = fongim_db_value(
            row["fongim_zone_id"]
        )

        region = fongim_db_value(
            row["region"]
        )

        cercle = fongim_db_value(
            row["cercle"]
        )

        commune = fongim_db_value(
            row["commune_raw"]
        )

        location_records.append({
            "record_key":
                fongim_stable_key(
                    project_id,
                    zone_id,
                    region,
                    cercle,
                    commune
                ),

            "fongim_project_id":
                project_id,
            "fongim_zone_id":
                zone_id,
            "region":
                region,
            "cercle":
                cercle,
            "commune_raw":
                commune,

            "last_seen_at":
                sync_time,
            "last_synced_at":
                sync_time,
            "is_present_in_source":
                True,
            "last_seen_sync_id":
                sync_run_id
        })

    fongim_validate_unique(
        location_records,
        "record_key",
        "Locations"
    )

    sector_records = []

    for _, row in sectors_df.iterrows():

        project_id = fongim_db_value(
            row["fongim_project_id"]
        )

        sector = fongim_db_value(
            row["sector"]
        )

        sector_other = fongim_db_value(
            row["sector_other_raw"]
        )

        sector_records.append({
            "record_key":
                fongim_stable_key(
                    project_id,
                    sector,
                    sector_other
                ),

            "fongim_project_id":
                project_id,
            "sector":
                sector,
            "sector_other_raw":
                sector_other,

            "last_seen_at":
                sync_time,
            "last_synced_at":
                sync_time,
            "is_present_in_source":
                True,
            "last_seen_sync_id":
                sync_run_id
        })

    fongim_validate_unique(
        sector_records,
        "record_key",
        "Sectors"
    )

    partner_records = []

    for _, row in partners_df.iterrows():

        project_id = fongim_db_value(
            row["fongim_project_id"]
        )

        partner_name = fongim_db_value(
            row["partner_name"]
        )

        organization_id = fongim_db_value(
            row[
                "fongim_organization_id"
            ]
        )

        partner_records.append({
            "record_key":
                fongim_stable_key(
                    project_id,
                    partner_name,
                    organization_id
                ),

            "fongim_project_id":
                project_id,

            "partner_name":
                partner_name,

            "fongim_organization_id":
                organization_id,

            "last_seen_at":
                sync_time,
            "last_synced_at":
                sync_time,
            "is_present_in_source":
                True,
            "last_seen_sync_id":
                sync_run_id
        })

    fongim_validate_unique(
        partner_records,
        "record_key",
        "Partners"
    )

    funding_records = []

    for _, row in funding_df.iterrows():

        key = fongim_stable_key(
            row["funding_id"],
            row["funding_index"],
            row["sector"]
        )

        funding_records.append({
            "record_key":
                key,

            "funding_id":
                fongim_db_value(
                    row["funding_id"]
                ),

            "funding_index":
                fongim_db_value(
                    row["funding_index"]
                ),

            "fongim_project_id":
                fongim_db_value(
                    row[
                        "fongim_project_id"
                    ]
                ),

            "organization_name":
                fongim_db_value(
                    row[
                        "organization_name"
                    ]
                ),

            "project_name_raw":
                fongim_db_value(
                    row[
                        "project_name_raw"
                    ]
                ),

            "project_type":
                fongim_db_value(
                    row["project_type"]
                ),

            "sector":
                fongim_db_value(
                    row["sector"]
                ),

            "funding_2024":
                fongim_db_value(
                    row["funding_2024"]
                ),

            "funding_2025":
                fongim_db_value(
                    row["funding_2025"]
                ),

            "linkage_status":
                fongim_db_value(
                    row["linkage_status"]
                ),

            "last_seen_at":
                sync_time,
            "last_synced_at":
                sync_time,
            "is_present_in_source":
                True,
            "last_seen_sync_id":
                sync_run_id
        })

    fongim_validate_unique(
        funding_records,
        "record_key",
        "Funding"
    )

    project_ids = {
        r["fongim_project_id"]
        for r in project_records
    }

    organization_ids = {
        r["fongim_organization_id"]
        for r in organization_records
    }

    project_child_sets = {
        "Project organizations": {
            r["fongim_project_id"]
            for r
            in project_organization_records
        },
        "Locations": {
            r["fongim_project_id"]
            for r in location_records
        },
        "Sectors": {
            r["fongim_project_id"]
            for r in sector_records
        },
        "Partners": {
            r["fongim_project_id"]
            for r in partner_records
        }
    }

    for name, ids in (
        project_child_sets.items()
    ):

        orphans = ids - project_ids

        if orphans:
            raise ValueError(
                f"{name}: orphan project IDs "
                f"detected: {sorted(orphans)}"
            )

    project_org_ids = {
        r["fongim_organization_id"]
        for r
        in project_organization_records
    }

    orphan_orgs = (
        project_org_ids
        - organization_ids
    )

    if orphan_orgs:
        raise ValueError(
            "Project organizations contain "
            "orphan organization IDs: "
            f"{sorted(orphan_orgs)}"
        )

    partner_org_ids = {
        r["fongim_organization_id"]
        for r in partner_records
        if r[
            "fongim_organization_id"
        ] is not None
    }

    orphan_partner_orgs = (
        partner_org_ids
        - organization_ids
    )

    if orphan_partner_orgs:
        raise ValueError(
            "Partners contain orphan "
            "organization IDs: "
            f"{sorted(orphan_partner_orgs)}"
        )

    print(
        "     ✓ All seven datasets prepared"
    )
    print(
        "     ✓ Cross-table integrity validated"
    )
    print()

    print(
        "     Projects:",
        len(project_records)
    )

    print(
        "     Organizations:",
        len(organization_records)
    )

    print(
        "     Project organizations:",
        len(
            project_organization_records
        )
    )

    print(
        "     Locations:",
        len(location_records)
    )

    print(
        "     Sectors:",
        len(sector_records)
    )

    print(
        "     Partners:",
        len(partner_records)
    )

    print(
        "     Funding:",
        len(funding_records)
    )

    print()
    print(
        "3/7  Registering sync run..."
    )

    sync_run_record = {
        "sync_run_id":
            sync_run_id,
        "source_system":
            metadata["source_system"],
        "source_url":
            metadata["source_url"],
        "source_model_id":
            metadata["source_model_id"],
        "sync_started_at":
            metadata["sync_started_at"],
        "sync_finished_at":
            metadata["sync_finished_at"],
        "status":
            "sync_started",

        "project_count":
            len(project_records),
        "location_count":
            len(location_records),
        "sector_count":
            len(sector_records),
        "organization_count":
            len(organization_records),

        "project_organization_count":
            len(
                project_organization_records
            ),

        "partner_count":
            len(partner_records),

        "funding_row_count":
            len(funding_records)
    }

    (
        supabase
        .table(
            "fongim_sync_runs"
        )
        .upsert(
            sync_run_record,
            on_conflict="sync_run_id"
        )
        .execute()
    )

    print(
        "     ✓ Sync run registered"
    )

    try:

        previous = (supabase.table("fongim_sync_runs")
                    .select("project_count,organization_count,location_count,sector_count,project_organization_count,partner_count,funding_row_count")
                    .eq("status", "success").order("sync_finished_at", desc=True).limit(1).execute()).data or []
        count_fields = ("project_count", "organization_count", "location_count", "sector_count",
                        "project_organization_count", "partner_count", "funding_row_count")
        validate_fongim_refresh({field: sync_run_record[field] for field in count_fields},
                               previous[0] if previous else {},
                               reviewed_shrink_reason=reviewed_shrink_reason)

        print(
            "4/7  Synchronizing "
            "parent tables..."
        )

        fongim_upsert_batches(
            "fongim_projects",
            project_records,
            "fongim_project_id"
        )

        fongim_upsert_batches(
            "fongim_organizations",
            organization_records,
            "fongim_organization_id"
        )

        print(
            "     ✓ Parent tables synchronized"
        )

        print(
            "5/7  Synchronizing "
            "relational tables..."
        )

        fongim_upsert_batches(
            "fongim_project_organizations",
            project_organization_records,
            "fongim_project_id"
        )

        fongim_upsert_batches(
            "fongim_project_locations",
            location_records,
            "record_key"
        )

        fongim_upsert_batches(
            "fongim_project_sectors",
            sector_records,
            "record_key"
        )

        fongim_upsert_batches(
            "fongim_project_partners",
            partner_records,
            "record_key"
        )

        fongim_upsert_batches(
            "fongim_project_funding",
            funding_records,
            "record_key"
        )

        print(
            "     ✓ Relational tables synchronized"
        )

        print(
            "6/7  Reconciling "
            "source presence..."
        )

        inactive_counts = {}

        inactive_counts[
            "projects"
        ] = fongim_mark_missing_inactive(
            "fongim_projects",
            "fongim_project_id",
            project_ids,
            sync_time
        )

        inactive_counts[
            "organizations"
        ] = fongim_mark_missing_inactive(
            "fongim_organizations",
            "fongim_organization_id",
            organization_ids,
            sync_time
        )

        inactive_counts[
            "project_organizations"
        ] = fongim_mark_missing_inactive(
            "fongim_project_organizations",
            "fongim_project_id",
            {
                r["fongim_project_id"]
                for r
                in project_organization_records
            },
            sync_time
        )

        inactive_counts[
            "locations"
        ] = fongim_mark_missing_inactive(
            "fongim_project_locations",
            "record_key",
            {
                r["record_key"]
                for r in location_records
            },
            sync_time
        )

        inactive_counts[
            "sectors"
        ] = fongim_mark_missing_inactive(
            "fongim_project_sectors",
            "record_key",
            {
                r["record_key"]
                for r in sector_records
            },
            sync_time
        )

        inactive_counts[
            "partners"
        ] = fongim_mark_missing_inactive(
            "fongim_project_partners",
            "record_key",
            {
                r["record_key"]
                for r in partner_records
            },
            sync_time
        )

        inactive_counts[
            "funding"
        ] = fongim_mark_missing_inactive(
            "fongim_project_funding",
            "record_key",
            {
                r["record_key"]
                for r in funding_records
            },
            sync_time
        )

        print(
            "     ✓ Source presence reconciled"
        )

        print(
            "7/7  Finalizing sync..."
        )

        (
            supabase
            .table(
                "fongim_sync_runs"
            )
            .update({
                "status":
                    "success"
            })
            .eq(
                "sync_run_id",
                sync_run_id
            )
            .execute()
        )

        print(
            "     ✓ Sync marked successful"
        )

        print()
        print("=" * 70)
        print("FONGIM SYNC COMPLETE")
        print("=" * 70)

        print(
            "Sync run:",
            sync_run_id
        )

        print(
            "Projects:",
            len(project_records)
        )

        print(
            "Organizations:",
            len(organization_records)
        )

        print(
            "Project organizations:",
            len(
                project_organization_records
            )
        )

        print(
            "Locations:",
            len(location_records)
        )

        print(
            "Sectors:",
            len(sector_records)
        )

        print(
            "Partners:",
            len(partner_records)
        )

        print(
            "Funding:",
            len(funding_records)
        )

        print()
        print(
            "Marked inactive:",
            inactive_counts
        )

        return {
            "sync_run_id":
                sync_run_id,

            "status":
                "success",

            "counts": {
                "projects":
                    len(project_records),

                "organizations":
                    len(
                        organization_records
                    ),

                "project_organizations":
                    len(
                        project_organization_records
                    ),

                "locations":
                    len(location_records),

                "sectors":
                    len(sector_records),

                "partners":
                    len(partner_records),

                "funding":
                    len(funding_records)
            },

            "marked_inactive":
                inactive_counts
        }

    except Exception as exc:

        (
            supabase
            .table(
                "fongim_sync_runs"
            )
            .update({
                "status":
                    "failed",
                "error_message":
                    str(exc)
            })
            .eq(
                "sync_run_id",
                sync_run_id
            )
            .execute()
        )

        print()
        print("FONGIM SYNC FAILED")
        print(
            "Sync run:",
            sync_run_id
        )
        print(
            "Error:",
            exc
        )

        raise
