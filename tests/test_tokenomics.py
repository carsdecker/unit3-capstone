# tests/test_tokenomics.py — Brief Step 6: every Claude call in a multi-tool query is
# logged with tokens + USD cost, and the state's totals agree with the call log.
# LIVE: one "both" question = 5 Claude calls.
import json
import pytest
from bedrock_client import CALL_LOG_PATH
from orchestrator import orchestrator

EXPECTED_COMPONENTS = {"classification", "sql_generation", "sql_interpretation",
                       "retrieval_answer", "synthesis"}


def read_call_log() -> list[dict]:
    try:
        with open(CALL_LOG_PATH) as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


@pytest.mark.live
def test_multi_tool_query_logs_every_claude_call():
    already_logged = len(read_call_log())
    state = orchestrator.invoke({
        "question": "How many active projects do we have, and what are the core hours in our remote work policy?",
        "route": None, "sql_result": None, "retrieval_result": None,
        "final_answer": None, "token_usage": None,
    })
    calls = read_call_log()[already_logged:]       # only the calls THIS query made

    print(f"\n  route: {state['route']}")
    print(f"  {'component':<20}{'input':>7}{'output':>8}{'cost_usd':>12}")
    for c in calls:
        print(f"  {c['component']:<20}{c['input_tokens']:>7}{c['output_tokens']:>8}{c['cost_usd']:>12.6f}")
    print(f"  state token_usage total: {state['token_usage']['total']}")

    # 1. Every expected call was made and logged -- once each, none unlabelled.
    assert state["route"] == "both"
    assert len(calls) == 5
    assert {c["component"] for c in calls} == EXPECTED_COMPONENTS

    # 2. Each call shows input tokens, output tokens and a USD cost.
    for c in calls:
        assert c["input_tokens"] > 0 and c["output_tokens"] > 0 and c["cost_usd"] > 0

    # 3. The state's per-component usage agrees with the call log.
    usage = state["token_usage"]
    assert set(usage) == EXPECTED_COMPONENTS | {"total"}
    assert usage["total"]["input"] == sum(c["input_tokens"] for c in calls)
    assert usage["total"]["output"] == sum(c["output_tokens"] for c in calls)
    assert usage["total"]["cost_usd"] == pytest.approx(sum(c["cost_usd"] for c in calls), abs=1e-5)