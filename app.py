
import os
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

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

openai_client = OpenAI(
    api_key=OPENAI_API_KEY
)


# ============================================================
# RETRIEVAL
# ============================================================

def search_knowledge_base(question, match_count=12):

    embedding_response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=question
    )

    query_embedding = embedding_response.data[0].embedding

    response = supabase.rpc(
        "match_chunks",
        {
            "query_embedding": query_embedding,
            "match_count": match_count
        }
    ).execute()

    raw_results = response.data or []

    document_ids = list({
        r.get("document_id")
        for r in raw_results
        if r.get("document_id")
    })

    documents_by_id = {}

    if document_ids:

        docs_response = (
            supabase
            .table("documents")
            .select(
                "id,title,organization,publication_date,"
                "valid_from,valid_until,document_type,"
                "language,geographic_scope,status,version"
            )
            .in_("id", document_ids)
            .execute()
        )

        documents_by_id = {
            d["id"]: d
            for d in docs_response.data
        }

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
            "document_type": doc.get("document_type"),
            "version": doc.get("version")
        })

    return results


# ============================================================
# EVIDENCE BUNDLE
# ============================================================

def build_evidence_bundle(results):

    evidence = []

    for i, r in enumerate(results, 1):

        evidence.append({
            "evidence_id": f"E{i}",
            "document_id": r.get("document_id"),
            "document_title": r.get("document_title"),
            "document_type": r.get("document_type"),
            "organization": r.get("organization"),
            "version": r.get("version"),
            "page": r.get("page_number"),
            "section": r.get("section_title"),
            "similarity": r.get("similarity"),
            "content": r.get("content")
        })

    return evidence


# ============================================================
# ANSWER ENGINE
# ============================================================

def generate_grounded_answer(
    question,
    match_count=12,
    model="gpt-5-mini"
):

    results = search_knowledge_base(
        question,
        match_count=match_count
    )

    evidence = build_evidence_bundle(results)

    evidence_text = ""

    for e in evidence:

        evidence_text += f"""
[{e['evidence_id']}]
DOCUMENT: {e['document_title']}
DOCUMENT_ID: {e['document_id']}
TYPE: {e['document_type']}
ORGANIZATION: {e['organization']}
VERSION: {e['version']}
PAGE: {e['page']}
SECTION: {e['section']}

CONTENT:
{e['content']}

---
"""

    system_prompt = """
You are the analytical engine of the Mali Knowledge Hub.

Answer questions using ONLY the evidence passages provided.

STRICT RULES:

1. Do not use outside knowledge.
2. Do not invent facts, policies, targets, relationships or citations.
3. Every substantive factual claim must be supported by the evidence.
4. Cite claims using the exact evidence IDs provided, for example [E3].
5. Never attribute a claim to a document unless that evidence passage
   explicitly comes from that document.
6. Distinguish carefully between:
   - current policy or strategic priorities
   - diagnosis of existing problems
   - targets
   - past results
   - recommendations
   - scenarios or hypothetical futures
7. Scenario passages describe hypothetical or alternative futures.
   They must NEVER be used as evidence for current conditions,
   current government policy, current priorities, or observed results.
   If relevant, they may only be discussed explicitly as scenarios.
8. If the evidence is insufficient, explicitly say so.
9. If documents differ in emphasis, preserve that distinction.
10. Prefer synthesis over simply listing retrieved passages.

At the end provide:

EVIDENCE STATUS: SUPPORTED
or
EVIDENCE STATUS: PARTIAL
or
EVIDENCE STATUS: INSUFFICIENT

Use the language of the user's question.
"""

    user_prompt = f"""
QUESTION:

{question}

EVIDENCE:

{evidence_text}

Answer the question based exclusively on this evidence.
"""

    response = openai_client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt
    )

    return {
        "answer": response.output_text,
        "evidence": evidence
    }


# ============================================================
# USER INTERFACE
# ============================================================

st.title("🇲🇱 Mali Knowledge Hub")

st.caption(
    "Evidence-grounded research across Mali's institutional knowledge base"
)

st.info(
    "Answers are generated exclusively from documents contained "
    "in the Knowledge Hub."
)

question = st.text_area(
    "Ask a question",
    placeholder=(
        "Example: What are Mali's priorities for decentralisation "
        "and local development?"
    ),
    height=120
)

ask = st.button(
    "Search Knowledge Hub",
    type="primary"
)


if ask and question.strip():

    with st.spinner(
        "Searching documents and analysing evidence..."
    ):

        try:

            result = generate_grounded_answer(
                question.strip()
            )

            st.subheader("Answer")

            st.markdown(
                result["answer"]
            )

            st.divider()

            st.subheader("Sources")

            for e in result["evidence"]:

                label = (
                    f"{e['evidence_id']} — "
                    f"{e['document_title']} · "
                    f"p. {e['page']}"
                )

                with st.expander(label):

                    if e["section"]:
                        st.markdown(
                            f"**Section:** {e['section']}"
                        )

                    if e["document_type"]:
                        st.markdown(
                            f"**Document type:** "
                            f"{e['document_type']}"
                        )

                    if e["version"]:
                        st.markdown(
                            f"**Version:** {e['version']}"
                        )

                    st.markdown("**Retrieved evidence:**")

                    st.write(
                        e["content"]
                    )

        except Exception as exc:

            st.error(
                f"Knowledge Hub error: {exc}"
            )

elif ask:

    st.warning(
        "Please enter a question."
    )
