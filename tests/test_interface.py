# tests/test_interface.py — Brief Step 2: both tools share one interface.
# LIVE: calls Claude (3 calls total: SQL generation + interpretation, retrieval answer).
# Run from the project root:  python -m pytest tests/test_interface.py -v -s
import pytest
from agents.sql_agent import run_sql_agent
from agents.retrieval_agent import run_retrieval_agent

EXPECTED_KEYS = {"success", "answer", "sources", "metadata"}


@pytest.mark.live
@pytest.mark.parametrize(
    "tool, question",
    [
        (run_sql_agent, "How many active projects do we have?"),
        (run_retrieval_agent, "How much can employees claim for home office equipment?"),
    ],
    ids=["sql_agent", "retrieval_agent"],
)
def test_tool_returns_standard_interface(tool, question):
    result = tool(question)
    print(f"\n  {tool.__name__} keys: {sorted(result.keys())}")

    # Exactly these four keys: no more, no fewer (a set comparison ignores order).
    assert set(result.keys()) == EXPECTED_KEYS
    # And each one has the type the orchestrator will rely on.
    assert isinstance(result["success"], bool)
    assert isinstance(result["answer"], str)
    assert isinstance(result["sources"], list)
    assert isinstance(result["metadata"], dict)
    # A relevant question should succeed, not just return the right shape.
    assert result["success"] is True