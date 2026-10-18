# tests/test_lambda_handler.py — Brief Step 8, checked LOCALLY before deploying.
# The assertions mirror Step 8's pass conditions for the real `aws lambda invoke`.
import json
import pytest
from lambda_handler import handler


def invoke(question=None) -> dict:
    # Build the same event shape `aws lambda invoke` sends: a JSON string inside "body".
    body = {} if question is None else {"question": question}
    return handler({"body": json.dumps(body)}, None)


def test_missing_question_returns_400():
    # FREE: rejected before any Claude call.
    response = invoke()
    print(f"\n  {response}")
    assert response["statusCode"] == 400


@pytest.mark.live
def test_both_question_meets_step8_pass_conditions():
    response = invoke("How many active projects do we have, and what are the core hours in our remote work policy?")
    body = json.loads(response["body"])
    print(f"\n  statusCode: {response['statusCode']}")
    print(f"  route: {body.get('route')} | sql_validation: {body.get('sql_validation')}")
    print(f"  token_usage total: {body.get('token_usage', {}).get('total')}")
    print(f"  answer: {body.get('answer')}")

    assert response["statusCode"] == 200, body
    assert body["route"] == "both"                          # Step 8: "route": "both"
    assert body["sql_validation"] == "PASSED"               # Step 8: "sql_validation": "PASSED"
    answer = body["answer"].lower()
    assert "sql agent" in answer and "retrieval agent" in answer   # combines both, with attribution
    assert body["token_usage"]["total"]["input"] > 0        # Step 8: non-zero token_usage

@pytest.mark.live
def test_two_turn_conversation_carries_history_through_the_handler():
    # Turn 1: no history sent.
    r1 = json.loads(invoke("How many active projects does Acme Corp have?")["body"])
    assert len(r1["history"]) == 1

    # Turn 2: send back exactly the history that turn 1 returned (the caller's job).
    event = {"body": json.dumps({"question": "What about their total contract value?",
                                 "history": r1["history"]})}
    r2 = json.loads(handler(event, None)["body"])
    print(f"\n  turn 2 answer: {r2['answer'][:200]}")
    print(f"  turn 2 history length: {len(r2['history'])}")
    assert "250000" in r2["answer"].replace(",", "")
    assert len(r2["history"]) == 2