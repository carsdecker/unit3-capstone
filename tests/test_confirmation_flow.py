# tests/test_confirmation_flow.py — Stretch Goal B through the REAL handler.
# FREE: Claude is faked. Queries that should run use the real database (no cost);
# where nothing may run, psycopg2.connect is a tripwire that fails the test.
import json
import pytest
import orchestrator
from agents import sql_agent
from lambda_handler import handler
from confirmation import sign

QUESTION = "Show me all invoices"
FLAGGED_SQL = "SELECT * FROM invoices"


def fake_claude(prompt, max_tokens=500, component="unlabelled"):
    text = "sql" if component == "classification" else "FAKE ANSWER"
    return {"text": text, "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}


def tripwire(*args, **kwargs):
    pytest.fail("The database was reached -- something ran that should not have!")


@pytest.fixture(autouse=True)
def fake_claude_everywhere(monkeypatch):
    monkeypatch.setattr(orchestrator, "invoke_claude", fake_claude)
    monkeypatch.setattr(sql_agent, "invoke_claude", fake_claude)


def call(body: dict) -> tuple[int, dict]:
    r = handler({"body": json.dumps(body)}, None)
    return r["statusCode"], json.loads(r["body"])


def generates(monkeypatch, sql):
    monkeypatch.setattr(sql_agent, "generate_sql",
                        lambda q, history=None: (sql, {"input": 1, "output": 1, "cost_usd": 0.0}))


def test_unusual_query_pauses_and_nothing_executes(monkeypatch):
    generates(monkeypatch, FLAGGED_SQL)
    monkeypatch.setattr(sql_agent.psycopg2, "connect", tripwire)
    status, body = call({"question": QUESTION})
    print(f"\n  needs_confirmation={body['needs_confirmation']} reason={body.get('reason')}")
    assert status == 200 and body["needs_confirmation"] is True
    assert body["sql"] == FLAGGED_SQL and body["reason"]
    assert body["sql_validation"] == "NEEDS_CONFIRMATION"
    assert set(body["confirm"]) == {"sql", "route", "token"}


def test_confirming_with_altered_sql_is_rejected(monkeypatch):
    generates(monkeypatch, FLAGGED_SQL)
    _, first = call({"question": QUESTION})
    altered = {**first["confirm"], "sql": "SELECT * FROM clients"}       # swapped query, same token
    monkeypatch.setattr(sql_agent.psycopg2, "connect", tripwire)
    status, body = call({"question": QUESTION, "confirm": altered})
    print(f"\n  altered confirmation -> {status}: {body.get('error')}")
    assert status == 403


def test_confirming_the_exact_query_runs_it(monkeypatch):
    generates(monkeypatch, FLAGGED_SQL)
    _, first = call({"question": QUESTION})
    # On confirmation, generation must NOT run again: the signed SQL is used as-is.
    monkeypatch.setattr(sql_agent, "generate_sql",
                        lambda *a, **k: pytest.fail("SQL was regenerated on confirmation!"))
    status, body = call({"question": QUESTION, "confirm": first["confirm"]})
    print(f"\n  exact confirmation -> {status}: validation={body['sql_validation']}")
    assert status == 200 and body["needs_confirmation"] is False
    assert body["sql_validation"] == "PASSED"                          # ran on the real database


def test_a_confirmed_query_is_still_validated(monkeypatch):
    # Even a correctly signed token for a destructive query is blocked by the validator.
    monkeypatch.setattr(sql_agent.psycopg2, "connect", tripwire)
    confirm = {"sql": "DROP TABLE invoices", "route": "sql", "token": sign("DROP TABLE invoices", "sql")}
    status, body = call({"question": QUESTION, "confirm": confirm})
    print(f"\n  signed DROP -> validation={body['sql_validation']}")
    assert status == 200 and body["sql_validation"] == "BLOCKED"


def test_routine_query_runs_without_confirmation(monkeypatch):
    generates(monkeypatch, "SELECT COUNT(*) FROM projects WHERE status = 'active'")
    status, body = call({"question": "How many active projects do we have?"})
    print(f"\n  routine -> needs_confirmation={body['needs_confirmation']} validation={body['sql_validation']}")
    assert status == 200 and body["needs_confirmation"] is False
    assert body["sql_validation"] == "PASSED"