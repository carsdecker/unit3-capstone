# tests/test_validator.py — Brief Step 5: the SQL validator blocks unsafe SQL.
# FREE: validate_sql() is plain Python -- no Claude, no database.
import pytest
from agents.sql_agent import validate_sql

# ---- The brief's five required cases --------------------------------------

def test_1_valid_select_is_allowed():
    assert validate_sql("SELECT name FROM clients WHERE region = 'North'")["valid"] is True


@pytest.mark.parametrize("sql", [
    "DROP TABLE clients",
    "DELETE FROM invoices",
    "UPDATE clients SET contract_value = 0",
    "INSERT INTO clients (name) VALUES ('x')",
])
def test_2_destructive_statement_is_blocked(sql):
    result = validate_sql(sql)
    print(f"\n  {sql!r} -> {result['reason']}")
    assert result["valid"] is False


def test_3_column_containing_blocked_word_is_allowed():
    # "deleted_at" contains DELETE as a substring. Allowing it proves the check
    # matches whole words, not substrings.
    assert validate_sql("SELECT id, deleted_at FROM clients")["valid"] is True


def test_4_stacked_query_with_blocked_keyword_is_blocked():
    result = validate_sql("SELECT * FROM clients; DROP TABLE clients")
    print(f"\n  -> {result['reason']}")
    assert result["valid"] is False


def test_5_stacked_query_without_blocked_keyword_is_blocked_by_stacking_check():
    # Neither half contains a blocked keyword, so only an independent stacking
    # check can catch this. Asserting on the REASON proves which rule fired.
    result = validate_sql("SELECT * FROM clients; SELECT * FROM invoices")
    print(f"\n  -> {result['reason']}")
    assert result["valid"] is False
    assert "multiple statements" in result["reason"]


# ---- Edge cases the brief's list implies -----------------------------------

def test_single_trailing_semicolon_is_allowed():
    # One statement ending in ";" is normal SQL, not stacking.
    assert validate_sql("SELECT * FROM clients;")["valid"] is True


def test_lowercase_destructive_statement_is_blocked():
    # Claude could write SQL in lowercase; the check must not depend on case.
    assert validate_sql("delete from invoices")["valid"] is False


# ---- "Try to break your own validator" (Trust but Verify lesson activity) -----

def test_select_into_is_blocked():
    # SELECT ... INTO creates a NEW TABLE from the results: a write that starts
    # with the word SELECT, so a "must start with SELECT" rule alone lets it through.
    result = validate_sql("SELECT * INTO clients_copy FROM clients")
    print(f"\n  -> valid={result['valid']} ({result['reason']})")
    assert result["valid"] is False


def test_cte_hiding_a_delete_is_blocked():
    # A WITH (CTE) clause can contain a DELETE that runs before the SELECT.
    result = validate_sql("WITH x AS (DELETE FROM invoices RETURNING *) SELECT * FROM x")
    print(f"\n  -> valid={result['valid']} ({result['reason']})")
    assert result["valid"] is False


def test_comment_hiding_a_second_statement_is_blocked():
    # "--" starts a comment; an attacker might hope the validator ignores the rest.
    result = validate_sql("SELECT * FROM clients -- ; DROP TABLE clients")
    print(f"\n  -> valid={result['valid']} ({result['reason']})")
    assert result["valid"] is False


def test_semicolon_inside_a_text_value_is_a_known_false_positive():
    # Harmless SQL: the ";" is inside a quoted value, not between statements.
    # The validator still blocks it -- it fails CLOSED (blocks when unsure).
    # Documented as acceptable: a blocked harmless query is safer than an allowed
    # dangerous one. This test pins that behaviour so any change is deliberate.
    result = validate_sql("SELECT * FROM clients WHERE name = 'A;B'")
    print(f"\n  -> valid={result['valid']} ({result['reason']})")
    assert result["valid"] is False