"""
lambda_handler.py -- wraps the orchestrator in the format Lambda expects.
(Course file from Deployment Patterns on AWS, plus Stretch Goals A and B.)

Stretch A: the CALLER carries the conversation -- it sends "history" and receives
the updated (capped) history to send with its next request.
Stretch B: an unusual query is paused and returned with a signed "confirm" block.
Sending that block back unchanged runs exactly that query (still validated); any
change to the SQL or route is rejected with 403.
"""
import json
from orchestrator import build_orchestrator
from tokenomics_logger import run_traced_query
from conversation import trim_history
from confirmation import sign, verify

orchestrator = build_orchestrator()


def handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        question = body.get("question", "").strip()

        if not question:
            return {"statusCode": 400, "body": json.dumps({"error": "question is required"})}

        # Caller-supplied, so trim_history also drops anything malformed.
        history = trim_history(body.get("history", []))

        confirm = body.get("confirm")
        if confirm is not None:
            # The trust boundary: only the exact flagged SQL + route may run.
            confirm = confirm if isinstance(confirm, dict) else {}
            sql, route, token = confirm.get("sql"), confirm.get("route"), confirm.get("token")
            if route not in ("sql", "both") or not isinstance(sql, str) or not verify(sql, route, token):
                return {"statusCode": 403, "body": json.dumps({
                    "error": "Confirmation rejected: the SQL or route does not match the query that was flagged."})}
            result = run_traced_query(orchestrator, question, history, confirmed_sql=sql, route=route)
        else:
            result = run_traced_query(orchestrator, question, history)

        sql_validation = None
        if result.get("sql_result"):
            sql_validation = result["sql_result"].get("metadata", {}).get("validation")

        updated_history = trim_history(history + [{"question": question, "answer": result["final_answer"]}])

        response = {
            "answer": result["final_answer"],
            "route": result["route"],
            "sql_validation": sql_validation,
            "token_usage": result.get("token_usage", {}),
            "history": updated_history,
            "needs_confirmation": False,
        }
                # Show which SQL ran (or was flagged), so a caller can check that a confirmation
        # executed exactly the query that was approved.
        if result.get("sql_result"):
            response["sql"] = result["sql_result"]["sources"][0].removeprefix("SQL: ")
            
        meta = (result.get("sql_result") or {}).get("metadata", {})
        if meta.get("needs_confirmation"):
            response.update({
                "needs_confirmation": True,
                "sql": meta["sql"],
                "reason": meta["reason"],
                # Send this block back unchanged (with the same question) to run the query.
                "confirm": {"sql": meta["sql"], "route": result["route"],
                            "token": sign(meta["sql"], result["route"])},
            })

        return {"statusCode": 200, "body": json.dumps(response)}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}