from uuid import UUID

import pytest

from qualification_corpus import QualificationCorpus, from_environment


def test_qualification_requires_distinct_credentials_and_host_verification(monkeypatch):
    monkeypatch.setenv("MKH_QUALIFICATION_CORPUS_DSN", "host=example.org user=qualification sslmode=require")
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="server certificate"):
        from_environment()
    monkeypatch.setenv("MKH_QUALIFICATION_CORPUS_DSN", "host=example.org user=qualification sslmode=verify-full")
    assert isinstance(from_environment(), QualificationCorpus)
    monkeypatch.setenv("OPENAI_API_KEY", "ordinary-runtime-fixture")
    with pytest.raises(RuntimeError, match="dedicated corpus"):
        from_environment()


def test_direct_corpus_bindings_read_only_and_keep_uuid_filters_typed(monkeypatch):
    corpus = QualificationCorpus("host=example.org")
    commands = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=()):
            commands.append((query.as_string() if hasattr(query, "as_string") else query, params))

        def __iter__(self):
            return iter([('{"id": "a"}',)])

    class DB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(corpus, "connect", lambda *a, **kw: DB())
    uid = "8f4950c2-33ac-474a-8c79-3cfbabcfac98"
    result = corpus.table("documents").select("id,title").in_("id", [uid]).range(0, 9).execute()
    assert result.data == [{"id": "a"}]
    assert commands[0][0] == "SET TRANSACTION READ ONLY"
    assert commands[2][1] == ([UUID(uid)], 10, 0)
    assert '"id" = ANY(%s)' in commands[2][0]
    corpus.rpc("match_chunks", {"query_embedding": [0.25], "match_count": 5,
                                "filter_document_ids": [uid]}).execute()
    assert "public.match_chunks" in commands[-1][0]
    assert commands[-1][1] == ("[0.25]", 5, [UUID(uid)])
    with pytest.raises(ValueError):
        corpus.rpc("publish_snapshot", {})
    with pytest.raises(ValueError):
        corpus.table("ingestion_jobs")
    assert not hasattr(corpus.table("documents"), "update")


def test_preflight_rejects_inherited_or_writable_login(monkeypatch):
    corpus = QualificationCorpus("host=example.org")

    class Cursor:
        def __init__(self):
            self.results = iter(((True,), (True,)))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query):
            pass

        def fetchone(self):
            return next(self.results)

    class DB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(corpus, "connect", lambda *a, **kw: DB())
    with pytest.raises(RuntimeError, match="write privileges"):
        corpus.verify_role()
