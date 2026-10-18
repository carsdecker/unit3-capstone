# tests/test_confirmation_live.py — Stretch Goal B + Gold, with REAL Claude, locally.
# LIVE: about 12 Claude calls in total.
import json
import pytest
from lambda_handler import handler


def call(body: dict) -> tuple[int, dict]:
    r = handler({"body": json.dumps(body)}, None)
    return r["statusCode"], json.loads(r["body"])


def show(label, status, body):
    print(f"\n  --- {label} --- status {status}")
    for key in ("route", "sql_validation", "needs_confirmation", "reason", "sql", "error"):
        if key in body:
            print(f"  {key}: {body[key]}")
    if "answer" in body:
        print(f"  answer: {body['answer'][:250]}")
    if "token_usage" in body:
        print(f"  token total: {body['token_usage'].get('total')}")


@pytest.mark.live
def test_stretch_b_pause_confirm_and_reject_altered():
    q = "Show me all invoices."
    status, flagged = call({"question": q})
    show("FLAGGED", status, flagged)
    assert flagged["needs_confirmation"] is True             # paused, nothing executed

    altered = {**flagged["confirm"], "sql": flagged["confirm"]["sql"] + " WHERE 1=1"}
    status, rejected = call({"question": q, "confirm": altered})
    show("ALTERED CONFIRMATION", status, rejected)
    assert status == 403

    status, confirmed = call({"question": q, "confirm": flagged["confirm"]})
    show("EXACT CONFIRMATION", status, confirmed)
    assert confirmed["sql_validation"] == "PASSED"
    assert confirmed["sql"] == flagged["sql"]                # ran exactly the approved query


@pytest.mark.live
def test_routine_question_is_unaffected():
    status, body = call({"question": "How many active projects do we have?"})
    show("ROUTINE", status, body)
    assert body["needs_confirmation"] is False and body["sql_validation"] == "PASSED"


@pytest.mark.live
def test_gold_memory_and_confirmation_together():
    # Turn 1 establishes the context (Acme Corp).
    _, t1 = call({"question": "How many active projects does Acme Corp have?"})
    show("GOLD TURN 1", 200, t1)

    # Turn 2: a follow-up using "their" that should produce a flagged (3-table) query.
    q2 = "Show me every invoice for their projects, with the project names."
    _, t2 = call({"question": q2, "history": t1["history"]})
    show("GOLD TURN 2 (follow-up)", 200, t2)
    assert t2["needs_confirmation"] is True
    assert "acme" in t2["sql"].lower()                       # flagged query reflects turn 1's context

    # Turn 3: confirm exactly that query, still carrying the conversation.
    _, t3 = call({"question": q2, "history": t2["history"], "confirm": t2["confirm"]})
    show("GOLD CONFIRMATION", 200, t3)
    assert t3["sql_validation"] == "PASSED"
    assert t3["sql"] == t2["sql"]                            # executed exactly the flagged query