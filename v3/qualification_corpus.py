"""Minimal read-only qualification adapter for the existing corpus retrieval calls."""
from dataclasses import dataclass, field
import json
import os
from types import SimpleNamespace
from uuid import UUID


TABLES = {
    "documents", "chunks", "fongim_organizations", "fongim_projects",
    "fongim_project_locations", "fongim_project_organizations",
    "fongim_project_sectors",
}


@dataclass
class Select:
    corpus: "QualificationCorpus"
    table: str
    columns: tuple = ()
    conditions: list = field(default_factory=list)
    start: int = 0
    size: int = 1000

    def select(self, columns):
        self.columns = tuple(column.strip() for column in columns.split(","))
        return self

    def eq(self, column, value):
        self.conditions.append((column, "=", value))
        return self

    def in_(self, column, values):
        self.conditions.append((column, "= ANY", list(values)))
        return self

    def range(self, start, end):
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end < start + 1000:
            raise ValueError("Invalid qualification corpus page")
        self.start, self.size = start, end - start + 1
        return self

    def execute(self):
        sql = self.corpus.sql
        if not self.columns:
            raise ValueError("Qualification exposes explicit reads only")
        if "*" in self.columns:
            raise ValueError("Qualification requires named evidence columns")
        fields = sql.SQL(", ").join(map(sql.Identifier, self.columns))
        statement = sql.SQL("SELECT row_to_json(q)::text FROM (SELECT {} FROM public.{}").format(
            fields, sql.Identifier(self.table)
        )
        args = []
        if self.conditions:
            clauses = []
            for column, operator, value in self.conditions:
                if operator == "= ANY":
                    if not value:
                        return SimpleNamespace(data=[])
                    clauses.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(column)))
                else:
                    clauses.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
                if self.table == "documents" and column == "id":
                    value = [UUID(str(item)) for item in value] if operator == "= ANY" else UUID(str(value))
                args.append(value)
            statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)
        # Underlying callers paginate; primary-key ordering avoids drift within each query.
        statement += sql.SQL(" ORDER BY {} LIMIT %s OFFSET %s) AS q").format(
            sql.Identifier(self.corpus.key_columns[self.table])
        )
        return self.corpus.read(statement, (*args, self.size, self.start))


class QualificationCorpus:
    key_columns = {
        "documents": "id", "chunks": "id",
        "fongim_organizations": "fongim_organization_id",
        "fongim_projects": "fongim_project_id",
        "fongim_project_locations": "record_key",
        "fongim_project_organizations": "fongim_project_id",
        "fongim_project_sectors": "record_key",
    }

    def __init__(self, dsn):
        import psycopg
        from psycopg import sql

        self.dsn = dsn
        self.sql = sql
        self.connect = psycopg.connect

    def verify_role(self):
        with self.connect(self.dsn, connect_timeout=8) as db, db.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("""
                SELECT NOT (rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls OR rolreplication)
                  AND NOT EXISTS (
                    SELECT 1 FROM pg_auth_members WHERE member = pg_roles.oid
                  )
                FROM pg_roles WHERE rolname = current_user
            """)
            if cursor.fetchone() != (True,):
                raise RuntimeError("Qualification login has elevated privileges or role memberships")
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE c.relkind IN ('r','p','v','m','f')
                      AND n.nspname IN ('public','storage','auth')
                      AND (has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER')
                        OR has_any_column_privilege(current_user,c.oid,'INSERT,UPDATE'))
                )
            """)
            if cursor.fetchone() != (False,):
                raise RuntimeError("Qualification login has write privileges on shared relations")
            for relation in sorted(TABLES):
                cursor.execute(self.sql.SQL("SELECT EXISTS (SELECT 1 FROM public.{})").format(
                    self.sql.Identifier(relation)
                ))
                if cursor.fetchone() != (True,):
                    raise RuntimeError(f"No visible qualification rows for {relation}")
            cursor.execute("SELECT has_function_privilege(current_user, "
                           "'public.match_chunks(public.vector,integer,uuid[])', 'EXECUTE')")
            if cursor.fetchone() != (True,):
                raise RuntimeError("Qualification vector search permission is missing")

    def table(self, name):
        if name not in TABLES:
            raise ValueError("Relation is outside the qualification corpus")
        return Select(self, name)

    def rpc(self, name, args):
        if name != "match_chunks" or set(args) != {"query_embedding", "match_count", "filter_document_ids"}:
            raise ValueError("Operation is outside the qualification corpus")
        vector = json.dumps(args["query_embedding"], allow_nan=False)
        sql = """SELECT row_to_json(q)::text
                 FROM public.match_chunks(%s::public.vector, %s::integer, %s::uuid[]) AS q"""
        ids = args["filter_document_ids"]
        params = (vector, args["match_count"], [UUID(str(item)) for item in ids] if ids is not None else None)
        return SimpleNamespace(execute=lambda: self.read(sql, params))

    def read(self, query, args):
        with self.connect(self.dsn, connect_timeout=8) as db, db.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '12s'")
            cursor.execute(query, args)
            return SimpleNamespace(data=[json.loads(value) for value, in cursor])


def from_environment():
    dsn = os.environ.get("MKH_QUALIFICATION_CORPUS_DSN")
    if not dsn or any(os.environ.get(name) for name in ("SUPABASE_SECRET_KEY", "OPENAI_API_KEY")):
        raise RuntimeError("Qualification requires a dedicated corpus login and no Supabase secret key")
    from psycopg.conninfo import conninfo_to_dict
    if conninfo_to_dict(dsn).get("sslmode") != "verify-full":
        raise RuntimeError("Qualification corpus connections must verify the server certificate and hostname")
    return QualificationCorpus(dsn)
