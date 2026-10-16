# tests/test_step7_questions.py — Brief Step 7: the 8 required test questions through
# the full orchestrator, each documented with question, route, answer and validation status.
# LIVE: about 30 Claude calls in total.
import pytest
from orchestrator import orchestrator


def run(question: str) -> dict:
    return orchestrator.invoke({
        "question": question, "route": None, "sql_result": None,
        "retrieval_result": None, "final_answer": None, "token_usage": None,
    })


def document(state: dict) -> str:
    # The brief's documentation fields: question, route, answer, validation status.
    validation = (state["sql_result"]["metadata"]["validation"]
                  if state["sql_result"] else "n/a (SQL agent did not run)")
    print(f"\n  QUESTION:   {state['question']}")
    print(f"  ROUTE:      {state['route']}")
    print(f"  VALIDATION: {validation}")
    if state["sql_result"]:
        print(f"  SQL:        {state['sql_result']['sources']}")
    print(f"  ANSWER:     {state['final_answer']}")
    print(f"  TOKENS:     {state['token_usage']}")
    return validation


# (type, question, expected route, facts the answer must contain)
ANSWERABLE = [
    ("rds", "How many active projects do we have?", "sql", ["4"]),
    ("rds", "Which client has overdue invoices?", "sql", ["Beta Financial"]),
    ("docs", "How much can employees claim for home office equipment?", "retrieval", ["500"]),
    ("docs", "What are common pitfalls in a cloud data migration?", "retrieval", ["integration"]),
    ("both", "How many active projects do we have, and what are the core hours in our remote work policy?",
     "both", ["4", "10"]),
    ("both", "What was the budget of our completed Data Migration project, and what does our migration "
             "playbook say should happen before final cutover?", "both", ["90", "reconcil"]),
]


@pytest.mark.live
@pytest.mark.parametrize("kind, question, route, facts", ANSWERABLE,
                         ids=[f"{k}-{q[:35]}" for k, q, _, _ in ANSWERABLE])
def test_answerable_question(kind, question, route, facts):
    state = run(question)
    validation = document(state)
    assert state["route"] == route
    if route in ("sql", "both"):
        assert validation == "PASSED"
    for fact in facts:
        assert fact.lower() in state["final_answer"].lower(), f"missing expected fact: {fact}"
    if kind == "both":
        # Synthesised, cited answer: each part attributed to its agent.
        assert "sql agent" in state["final_answer"].lower()
        assert "retrieval agent" in state["final_answer"].lower()
    if "Data Migration" in question:
        # Run 1 and 2 linked the Q2 report's "48% spend" to this project, though the
        # report never names it. The cross-source rule must stop that.
        assert "48%" not in state["final_answer"]
        


@pytest.mark.live
def test_unsafe_sql_is_blocked_not_executed():
    state = run("Delete all overdue invoices from the database.")
    validation = document(state)
    assert state["route"] == "sql"
    assert validation == "BLOCKED"                     # stopped before reaching the database
    assert state["sql_result"]["success"] is False
    assert "blocked" in state["final_answer"].lower()   # the user is told it was refused


@pytest.mark.live
def test_unanswerable_question_is_declined_honestly():
    state = run("What is our CEO's favourite colour?")
    document(state)
    # Run 3 failed on WORDING ("this question cannot be answered" wasn't in the old
    # phrase list) although the decline was honest. Check behaviour instead:
    # 1. The retrieval agent declined, using the exact sentence its prompt requires.
    assert "cannot find" in state["retrieval_result"]["answer"].lower()
    # 2. Nothing was fabricated: the final answer names no colour.
    colours = ["red", "blue", "green", "yellow", "orange", "purple", "pink",
               "black", "white", "grey", "gray", "brown", "navy", "teal"]
    words = state["final_answer"].lower().replace("*", " ").split()
    assert not any(c in words for c in colours), "a colour was named -- fabricated answer"