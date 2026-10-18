# tests/test_memory_live.py — Stretch Goal A: the brief's two-turn exchange, run locally.
# LIVE: 3 orchestrator runs (turn 1, turn 2 without memory as a control, turn 2 with memory).
import pytest
from orchestrator import orchestrator

TURN_1 = "How many active projects does Acme Corp have?"
TURN_2 = "What about their total contract value?"


def run(question, history=None):
    return orchestrator.invoke({
        "question": question, "route": None, "sql_result": None, "retrieval_result": None,
        "final_answer": None, "token_usage": None, "history": history or [],
    })


def show(label, state):
    usage = state["token_usage"]
    sql = state["sql_result"]["sources"] if state["sql_result"] else None
    print(f"\n  --- {label} ---")
    print(f"  route: {state['route']} | SQL: {sql}")
    print(f"  answer: {state['final_answer'][:300]}")
    print(f"  classification input tokens: {usage['classification']['input']}")
    if "sql_generation" in usage:
        print(f"  sql_generation input tokens: {usage['sql_generation']['input']}")
    print(f"  total: {usage['total']}")


@pytest.mark.live
def test_follow_up_is_resolved_by_memory():
    turn1 = run(TURN_1)
    show("TURN 1", turn1)
    history = [{"question": TURN_1, "answer": turn1["final_answer"]}]

    control = run(TURN_2)                      # same question, NO history
    show("TURN 2 WITHOUT MEMORY (control)", control)

    turn2 = run(TURN_2, history)               # same question, WITH history
    show("TURN 2 WITH MEMORY", turn2)

    # Memory cost: same question, so the difference is exactly the replayed history.
    for part in ("classification", "sql_generation"):
        extra = turn2["token_usage"][part]["input"] - control["token_usage"][part]["input"]
        print(f"  memory added to {part}: +{extra} input tokens")

    assert turn1["route"] == "sql"
    assert turn2["route"] == "sql"
    sql = " ".join(turn2["sql_result"]["sources"]).lower()
    assert "acme" in sql                                   # filtered to Acme Corp...
    answer = turn2["final_answer"].replace(",", "")
    assert "250000" in answer                              # ...giving its $250,000
    assert "1515000" not in answer                         # not the all-clients total