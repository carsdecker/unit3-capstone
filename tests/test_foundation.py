# tests/test_foundation.py — Brief Step 1: confirm each data store works on its own.
# Integration tests: they query the REAL RDS database and OpenSearch domain.
# No Claude calls, so no token cost.
# Run from the project root:  python -m pytest tests/test_foundation.py -v -s
import os
import psycopg2
import pytest
from dotenv import load_dotenv
from ingest_documents import get_opensearch_client, INDEX_NAME
from onnx_embed import get_embedding

load_dotenv()

TABLES = ["clients", "projects", "consultants", "invoices"]


@pytest.fixture(scope="module")
def db():
    # A fixture is shared setup: one database connection, reused by every test
    # in this file, and closed once at the end.
    conn = psycopg2.connect(
        host=os.getenv("RDS_HOST"), port=int(os.getenv("RDS_PORT")),
        dbname=os.getenv("RDS_DATABASE"), user=os.getenv("RDS_USER"),
        password=os.getenv("RDS_PASSWORD"), sslmode="require",
    )
    yield conn
    conn.close()


@pytest.mark.parametrize("table", TABLES)
def test_rds_table_has_rows(db, table):
    # parametrize runs this test once per table, so each table passes or fails on its own.
    # Building SQL with an f-string is safe here only because `table` comes from our
    # fixed TABLES list, never from user input.
    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
    print(f"\n  RDS {table}: {count} rows")
    assert count > 0


def test_opensearch_index_has_documents():
    count = get_opensearch_client().count(index=INDEX_NAME)["count"]
    print(f"\n  OpenSearch '{INDEX_NAME}': {count} chunks")
    assert count > 0


def test_opensearch_finds_the_right_document():
    # Beyond the brief: an index can be populated but useless if stored vectors and
    # query vectors don't match. A stipend question must find the remote work policy.
    vector = get_embedding("How much can employees claim for home office equipment?")
    hits = get_opensearch_client().search(
        index=INDEX_NAME,
        body={"size": 1, "query": {"knn": {"embedding": {"vector": vector, "k": 1}}}},
    )["hits"]["hits"]
    print(f"\n  top hit: {hits[0]['_source']['source']} (score {hits[0]['_score']:.3f})")
    assert hits[0]["_source"]["source"] == "remote-work-policy.pdf"