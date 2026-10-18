# tests/test_no_bypass.py — Brief Step 5: there is no path to the database that
# skips the validator. FREE: Claude and the database are both replaced with fakes.
import ast
from pathlib import Path
import pytest
from agents import sql_agent


def tripwire(*args, **kwargs):
    # Stands in for psycopg2.connect: if anything reaches the database, the test fails.
    pytest.fail("Database connection attempted -- the validator was bypassed!")


def test_execute_query_safely_validates_before_connecting(monkeypatch):
    monkeypatch.setattr(sql_agent.psycopg2, "connect", tripwire)
    result = sql_agent.execute_query_safely("DROP TABLE clients")
    print(f"\n  -> {result['validation']}: {result['error']}")
    assert result["validation"] == "BLOCKED"       # stopped by the validator, never connected


def test_full_sql_agent_path_blocks_before_the_database(monkeypatch):
    # "Claude" (faked, free) generates a destructive query; the whole agent runs.
    monkeypatch.setattr(sql_agent, "generate_sql",
                    lambda question, history=None: ("DELETE FROM invoices", {"input": 0, "output": 0, "cost_usd": 0.0}))
    monkeypatch.setattr(sql_agent.psycopg2, "connect", tripwire)
    monkeypatch.setattr(sql_agent, "invoke_claude",
                    lambda *a, **k: pytest.fail("Interpretation ran on a blocked query!"))
    result = sql_agent.run_sql_agent("Please delete all invoices")
    print(f"\n  -> success={result['success']} validation={result['metadata']['validation']}")
    assert result["success"] is False
    assert result["metadata"]["validation"] == "BLOCKED"


def test_only_one_database_connection_exists_in_the_agent_code():
    # A second psycopg2.connect anywhere in the system would be a back door
    # around execute_query_safely. Scan every file the orchestrator can reach.
    files = list(Path("agents").glob("*.py")) + [Path("orchestrator.py"), Path("tool_registry.py")]
    found = []
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for inner in ast.walk(node):
                    if (isinstance(inner, ast.Attribute) and inner.attr == "connect"
                            and getattr(inner.value, "id", None) == "psycopg2"):
                        found.append(f"{path}:{node.name}")
    print(f"\n  psycopg2.connect found in: {found}")
    assert found == ["agents/sql_agent.py:execute_query_safely"]