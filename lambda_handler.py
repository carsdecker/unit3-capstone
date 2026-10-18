"""
lambda_handler.py -- wraps the orchestrator in the format Lambda expects.
(Course file from Deployment Patterns on AWS, plus Stretch Goal A conversation memory.)

Lambda keeps no memory between invocations, so the CALLER carries the conversation:
it sends "history" (prior {question, answer} turns) and receives the updated history,
capped to the last few turns (see conversation.py), to send with its next request.
"""
import json
from orchestrator import build_orchestrator
from tokenomics_logger import run_traced_query
from conversation import trim_history

orchestrator = build_orchestrator()


def handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        question = body.get("question", "").strip()

        if not question:
            return {"statusCode": 400, "body": json.dumps({"error": "question is required"})}

        # Caller-supplied, so trim_history also drops anything malformed.
        history = trim_history(body.get("history", []))
        result = run_traced_query(orchestrator, question, history)

        sql_validation = None
        if result.get("sql_result"):
            sql_validation = result["sql_result"].get("metadata", {}).get("validation")

        updated_history = trim_history(history + [{"question": question, "answer": result["final_answer"]}])

        return {
            "statusCode": 200,
            "body": json.dumps({
                "answer": result["final_answer"],
                "route": result["route"],
                "sql_validation": sql_validation,
                "token_usage": result.get("token_usage", {}),
                "history": updated_history
            })
        }
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}