# tests/test_orchestrator.py — Brief Step 4: the full LangGraph orchestrator, end to end.
# LIVE integration test: real Claude (Bedrock), real RDS, real OpenSearch.
# About 12 Claude calls in total across the three questions.
import pytest
from orchestrator import orchestrator


def run(question: str) -> dict:
    return orchestrator.invoke({
        "question": question, "route": None, "sql_result": None,
        "retrieval_result": None, "final_answer": None, "token_usage": None,
    })


def show(state: dict):
    # The brief's evidence is the printed state; agent results are summarised
    # (success + answer) rather than dumped in full.
    print(f"\n  route: {state['route']}")
    for key in ("sql_result", "retrieval_result"):
        r = state[key]
        print(f"  {key}: " + ("None (agent did not run)" if r is None
                               else f"success={r['success']} answer={r['answer'][:120]!r}"))
    print(f"  final_answer: {state['final_answer']}")
    print(f"  token_usage: {state['token_usage']}")


@pytest.mark.live
def test_sql_only_question_runs_only_the_sql_agent():
    state = run("How many active projects do we have?")
    show(state)
    assert state["route"] == "sql"
    assert state["sql_result"] is not None and state["sql_result"]["success"]
    assert state["retrieval_result"] is None          # only the needed tool ran
    assert "4" in state["final_answer"]               # answer key: 4 active projects


@pytest.mark.live
def test_retrieval_only_question_runs_only_the_retrieval_agent():
    state = run("How much can employees claim for home office equipment?")
    show(state)
    assert state["route"] == "retrieval"
    assert state["retrieval_result"] is not None and state["retrieval_result"]["success"]
    assert state["sql_result"] is None                # only the needed tool ran
    assert "500" in state["final_answer"]             # answer key: $500 per year


@pytest.mark.live
def test_both_question_synthesises_and_attributes_each_agent():
    state = run("How many active projects do we have, and what are the core hours in our remote work policy?")
    show(state)
    assert state["route"] == "both"
    assert state["sql_result"] is not None and state["sql_result"]["success"]
    assert state["retrieval_result"] is not None and state["retrieval_result"]["success"]
    answer = state["final_answer"]
    assert "4" in answer and "10" in answer           # 4 active projects; core hours from 10:00 AM
    # Attribution: the brief requires each part credited to its agent.
    assert "sql agent" in answer.lower()
    assert "retrieval agent" in answer.lower()