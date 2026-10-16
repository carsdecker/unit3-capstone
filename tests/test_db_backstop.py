# tests/test_db_backstop.py — defence in depth below the validator.
# Uses the REAL RDS database (no Claude calls, no cost). The validator is
# deliberately switched off with monkeypatch so each test proves the DATABASE
# layer blocks the query on its own.
from agents import sql_agent


def allow_everything(query):
    return {"valid": True, "reason": "validator bypassed for this test"}


def test_database_refuses_a_write_even_if_the_validator_misses_it(monkeypatch):
    monkeypatch.setattr(sql_agent, "validate_sql", allow_everything)
    result = sql_agent.execute_query_safely("SELECT * INTO clients_copy FROM clients")
    print(f"\n  -> {result['validation']}: {result.get('error', '')[:100]}")
    assert result["success"] is False
    assert "read-only" in result["error"]


def test_database_cancels_a_slow_query(monkeypatch):
    # pg_sleep(12) waits 12 seconds; the 10-second statement_timeout must stop it first.
    monkeypatch.setattr(sql_agent, "validate_sql", allow_everything)
    result = sql_agent.execute_query_safely("SELECT pg_sleep(12)")
    print(f"\n  -> {result['validation']}: {result.get('error', '')[:100]}")
    assert result["success"] is False
    assert "statement timeout" in result["error"]


def test_normal_reads_still_work():
    # The backstop must not break legitimate queries (validator left ON here).
    result = sql_agent.execute_query_safely("SELECT COUNT(*) FROM projects WHERE status = 'active'")
    print(f"\n  -> {result['validation']}: rows={result.get('rows')}")
    assert result["success"] is True
    assert result["rows"] == [(4,)]