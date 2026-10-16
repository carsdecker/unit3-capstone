# tests/test_routing.py — routing correctness for the classification node.
# LIVE: route_question() makes one small Claude call per question.
import pytest
from orchestrator import route_question

# Original 9: the keyword router failed 3 of these (evidence/routing_keyword_baseline.txt).
ORIGINAL = [
    ("How many active projects do we have?", "sql"),
    ("Which clients have overdue invoices?", "sql"),
    ("What is the total contract value across all clients?", "sql"),
    ("What is the budget for the Fraud Detection System project?", "sql"),
    ("How much can employees claim for home office equipment?", "retrieval"),
    ("What are the core hours in the remote work policy?", "retrieval"),
    ("What percentage of historical records had been migrated by Q2?", "retrieval"),
    ("What are common pitfalls in a cloud data migration?", "retrieval"),
    ("How many active projects do we have, and what are the core hours in our remote work policy?", "both"),
]

# Held out: written AFTER the router change and never used to tune it. If these
# pass too, the router generalises instead of fitting the 9 above.
HELD_OUT = [
    ("What's our total billing that is still unpaid?", "sql"),
    ("Can I expense my internet bill when working from home?", "retrieval"),
    ("Which consultant has logged the most billable hours?", "sql"),
    ("What results did the grocery client see after the forecasting rollout?", "retrieval"),
    ("Which of our projects are on hold, and what does our migration playbook recommend before cutover?", "both"),
    ("What is the CEO's favourite colour?", "retrieval"),
]


@pytest.mark.live
@pytest.mark.parametrize("question, expected", ORIGINAL + HELD_OUT,
                         ids=[q[:45] for q, _ in ORIGINAL + HELD_OUT])
def test_router_picks_correct_route(question, expected):
    state = {"question": question, "route": None, "sql_result": None,
             "retrieval_result": None, "final_answer": None, "token_usage": None}
    result = route_question(state)
    usage = result["token_usage"]["classification"]
    print(f"\n  route={result['route']!r} (expected {expected!r})  tokens in/out {usage['input']}/{usage['output']}")
    assert result["route"] == expected