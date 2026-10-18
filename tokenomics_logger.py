"""
tokenomics_logger.py -- structured logging and full-chain tracing for the
orchestrator, kept separate from orchestrator.py itself, the same way
bedrock_client.py stays separate from every agent that calls it.
(Course file from Deployment Patterns on AWS, plus Stretch Goals A and B.)
"""
import json
import uuid
from datetime import datetime
from orchestrator import route_question


def log_decision(stage: str, question: str, details: dict):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "stage": stage,
        "question": question,
        "details": details
    }
    print(f"[LOG] {stage}: {json.dumps(details)}")
    with open("/tmp/agent_decisions.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def route_question_logged(state):
    result = route_question(state)
    log_decision("routing", state["question"], {"route": result["route"]})
    return result


def run_traced_query(orchestrator, question: str, history: list = None,
                     confirmed_sql: str = None, route: str = None) -> dict:
    trace_id = str(uuid.uuid4())[:8]

    # Stretch Goal A: how many earlier turns came in with this question.
    # Stretch Goal B: whether this request is a confirmation of a flagged query.
    log_decision("query_start", question, {"trace_id": trace_id,
                                           "history_turns": len(history or []),
                                           "confirmed": confirmed_sql is not None})

    result = orchestrator.invoke({
        "question": question, "route": route, "sql_result": None,
        "retrieval_result": None, "final_answer": None, "token_usage": None,
        "history": history or [], "confirmed_sql": confirmed_sql,
    })

    # NOTE: sql_result's "validation" field is nested under "metadata", not
    # top-level. Accessing result["sql_result"]["validation"] directly silently
    # returns None even on a query that actually passed.
    log_decision("query_complete", question, {
        "trace_id": trace_id,
        "route": result["route"],
        "sql_validation": result.get("sql_result", {}).get("metadata", {}).get("validation") if result.get("sql_result") else None,
        "retrieval_chunk_count": len(result.get("retrieval_result", {}).get("sources", [])) if result.get("retrieval_result") else None,
        "token_usage": result.get("token_usage")
    })

    return result