# tests/test_confirmation.py — Stretch Goal B: "unusual" criteria + confirmation tokens.
# FREE: plain Python, no Claude, no database.
import pytest
import confirmation
from confirmation import unusual_reason, sign, verify

# ---- Criteria: what counts as unusual --------------------------------------

@pytest.mark.parametrize("sql", [
    "SELECT * FROM invoices",                                    # whole-table dump
    "SELECT name, region FROM clients",                          # still every row
    "SELECT c.name FROM clients c JOIN projects p ON p.client_id = c.id "
    "JOIN invoices i ON i.project_id = p.id WHERE i.status = 'overdue'",   # 3 tables
])
def test_unusual_queries_are_flagged(sql):
    reason = unusual_reason(sql)
    print(f"\n  FLAGGED: {sql[:60]}... -> {reason}")
    assert reason is not None


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM projects WHERE status = 'active'",     # filtered aggregate
    "SELECT SUM(contract_value) FROM clients",                   # aggregate = one row
    "SELECT * FROM invoices LIMIT 5",                            # bounded by LIMIT
    "SELECT name FROM clients WHERE region = 'North'",           # filtered
    "SELECT p.name FROM projects p JOIN clients c ON p.client_id = c.id "
    "WHERE c.name = 'Acme Corp'",                                # 2 tables only
])
def test_routine_queries_are_not_flagged(sql):
    assert unusual_reason(sql) is None


# ---- Tokens: a confirmation can only run the exact flagged query ------------

SQL = "SELECT * FROM invoices"


def test_token_verifies_for_the_exact_query():
    assert verify(SQL, "sql", sign(SQL, "sql")) is True


def test_token_rejects_an_altered_query():
    token = sign(SQL, "sql")
    assert verify("SELECT * FROM clients", "sql", token) is False       # different table
    assert verify(SQL + " ", "sql", token) is False                      # even one space


def test_token_rejects_an_altered_route():
    assert verify(SQL, "both", sign(SQL, "sql")) is False


def test_missing_or_garbage_token_is_rejected():
    assert verify(SQL, "sql", None) is False
    assert verify(SQL, "sql", "0" * 64) is False


def test_without_a_secret_nothing_can_be_signed(monkeypatch):
    monkeypatch.delenv("CONFIRMATION_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        sign(SQL, "sql")                                                 # fails closed