from types import SimpleNamespace

import knowledge_hub_runtime as runtime
from passage_ranking import rerank_passages
from synthesis_context import prepare


def test_document_search_rescues_exact_identifier_in_one_read(monkeypatch):
    calls = []
    semantic = [
        {"id": "a", "document_id": "doc", "content": "Regional health budget", "similarity": .9},
        {"id": "b", "document_id": "doc", "content": "Broad planning context", "similarity": .8},
        {"id": "c", "document_id": "doc", "content": "Project P123456 planned closure", "similarity": .7},
        {"id": "d", "document_id": "doc", "content": "Project P1234567 planned closure", "similarity": .6},
    ]

    def rpc(name, arguments):
        calls.append((name, arguments))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=semantic))

    def embed(**arguments):
        calls.append(("embedding", arguments))
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1])])

    monkeypatch.setattr(runtime, "supabase", SimpleNamespace(rpc=rpc))
    monkeypatch.setattr(runtime, "openai_client", SimpleNamespace(embeddings=SimpleNamespace(create=embed)))
    rows = runtime.search_knowledge_base(
        "semantic source guidance", 2, ["doc"],
        document_metadata={"doc": {"title": "Portfolio", "publication_date": "2025-08-01"}},
        lexical_question="What is the closing date for P123456?",
    )
    assert [row["id"] for row in rows] == ["a", "c"]
    assert rows[1]["lexical_rescue"] and "lexical_rescue" not in semantic[2]
    assert rows[1]["publication_date"] == "2025-08-01"
    assert [name for name, _ in calls] == ["embedding", "match_chunks"]
    assert calls[1][1]["match_count"] == 4 and calls[1][1]["filter_document_ids"] == ["doc"]


def test_no_weak_lexical_substitution_and_rescue_survives_synthesis():
    originals = [{"id": str(i), "content": content} for i, content in enumerate(
        ["Broad planning context", "Priority activities overview", "Budget figures"]
    )]
    assert rerank_passages(originals, "Budget details for P123456", 2) == originals[:2]
    ledger = [
        {"evidence_id": f"E{i:02d}", "document_id": "doc", "page": i,
         "source_type": "knowledge_base_document", "content": "Detailed finance budget requirements"}
        for i in range(1, 6)
    ]
    ledger.append({**ledger[-1], "evidence_id": "E06", "page": 6,
                   "content": "The exact project P123456 closes in 2025.", "lexical_rescue": True})
    view, _ = prepare(ledger, "Compare finance budget requirements for P123456.")
    assert len(view) == 4
    assert "E06" in {row["evidence_id"] for row in view}
