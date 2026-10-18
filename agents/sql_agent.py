"""
agents/sql_agent.py -- validated SQL Query Agent, wrapped to the standard
{success, answer, sources, metadata} interface from the Shared Tool Registry lab.
(Course file from Deployment Patterns on AWS, with the changes noted below.)

Self-contained: generate_sql, validate_sql and execute_query_safely are all in
this file, so it works inside a Lambda package with nothing else bundled
(plus conversation.py for Stretch Goal A).
"""
import os
import psycopg2
from dotenv import load_dotenv
from bedrock_client import invoke_claude
from conversation import format_history
from confirmation import unusual_reason
load_dotenv()

# "status in invoices" added after Step 7: asked "Which client has overdue invoices?",
# Claude invented its own definition (status != 'paid' AND due_date < today) because
# only the projects statuses were documented.
SCHEMA_CONTEXT = """
Tables available:
- clients(id, name, industry, region, contract_value, created_date)
- projects(id, client_id, name, status, start_date, end_date, budget)
- consultants(id, name, grade, specialisation, project_id, billable_hours)
- invoices(id, project_id, amount, status, due_date, paid_date)

All monetary values are in USD. Dates are in ISO 8601 format.
status in projects is one of: 'active', 'completed', 'on-hold'.
status in invoices is one of: 'paid', 'pending', 'overdue'.
"""

# "INTO" added after tests/test_validator.py found "SELECT * INTO clients_copy FROM clients"
# passing every rule: it starts with SELECT and has no other blocked word, yet PostgreSQL
# runs it as CREATE TABLE + copy -- a write. (INSERT INTO is already caught by INSERT.)
BLOCKED_KEYWORDS = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
                    "EXEC", "EXECUTE", "GRANT", "REVOKE", "INTO"]


def validate_sql(query: str) -> dict:
    """
    Blocks any query that isn't a SELECT, contains a destructive keyword, or
    stacks multiple statements. This must run before any database call.
    """
    query_upper = query.upper().strip()

    # Whole-word match: padding with spaces means "DELETE" matches the word
    # DELETE but not a column like "deleted_at".
    for keyword in BLOCKED_KEYWORDS:
        if f" {keyword} " in f" {query_upper} " or query_upper.startswith(keyword):
            return {"valid": False, "reason": f"Blocked: '{keyword}' is not permitted."}

    if not query_upper.startswith("SELECT"):
        return {"valid": False, "reason": "Only SELECT queries are permitted."}

    # Block stacked queries independently of keyword content -- a stacked
    # query with two harmless-looking SELECTs would sail past every keyword
    # check above, since there's nothing destructive in either half.
    stripped = query.strip().rstrip(";")
    if ";" in stripped:
        return {"valid": False, "reason": "Blocked: multiple statements detected."}

    return {"valid": True, "reason": "OK"}


def generate_sql(question: str, history: list = None) -> tuple[str, dict]:
    # Stretch Goal A: earlier turns are replayed (capped, see conversation.py) so a
    # follow-up like "What about their total contract value?" can be resolved to the
    # client named earlier, instead of becoming a total across all clients.
    prompt = (
        f"{SCHEMA_CONTEXT}\n\n"
        f"{format_history(history)}"
        f"Generate a SQL query to answer: {question}\n\n"
        "If the question refers to something from the conversation (e.g. 'their', "
        "'that project'), use the conversation to resolve it.\n"
        "Return ONLY the SQL query. No explanation, no markdown, no backticks."
    )
    result = invoke_claude(prompt, max_tokens=512, component="sql_generation")
    sql = result["text"].strip()
    sql = sql.removeprefix("```sql").removeprefix("```").removesuffix("```").strip()
    # Step 6 fix: the course version discarded this call's token usage, so the
    # schema-bearing generation prompt never appeared in any cost figure.
    usage = {"input": result["input_tokens"], "output": result["output_tokens"],
             "cost_usd": result["cost_usd"]}
    return sql, usage


def execute_query_safely(sql: str) -> dict:
    # The validator runs FIRST, inside this function, so there is no path to
    # the database that skips it (brief Step 5).
    validation = validate_sql(sql)
    if not validation["valid"]:
        return {"success": False, "error": validation["reason"], "validation": "BLOCKED", "sql": sql}

    try:
        # Defence in depth: PostgreSQL itself enforces read-only and a time limit on
        # this connection, so a write that slips past validate_sql (as SELECT ... INTO
        # did in testing) is refused by the database, and a slow query (e.g. pg_sleep,
        # which validate_sql allows) is cancelled after 10 seconds.
        conn = psycopg2.connect(
            host=os.getenv("RDS_HOST"), port=int(os.getenv("RDS_PORT")),
            dbname=os.getenv("RDS_DATABASE"), user=os.getenv("RDS_USER"),
            password=os.getenv("RDS_PASSWORD"),
            options="-c default_transaction_read_only=on -c statement_timeout=10000"
        )
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return {"success": True, "columns": cols, "rows": rows, "validation": "PASSED", "sql": sql}
    except Exception as e:
        return {"success": False, "error": str(e), "validation": "EXECUTION_ERROR", "sql": sql}


def validated_sql_agent(question: str, history: list = None, confirmed_sql: str = None) -> dict:
    if confirmed_sql is None:
        sql, gen_usage = generate_sql(question, history)
        token_usage = {"sql_generation": gen_usage}
        # Stretch Goal B: review step between generation and execution. A query that
        # PASSES validation but is unusual (see confirmation.py) is not executed; it is
        # returned for a person to confirm. (A query that fails validation skips this
        # and is blocked by execute_query_safely as usual.)
        if validate_sql(sql)["valid"]:
            reason = unusual_reason(sql)
            if reason:
                return {"answer": f"Query needs confirmation: {reason}", "sql": sql,
                        "validation": "NEEDS_CONFIRMATION", "reason": reason,
                        "token_usage": token_usage}
    else:
        # A confirmed query (its token was verified by the handler) skips generation
        # and the review step -- but NOT the validator, which runs inside
        # execute_query_safely exactly as for every other query.
        sql, token_usage = confirmed_sql, {}

    result = execute_query_safely(sql)

    if not result["success"]:
        return {
            "answer": f"Query blocked or failed: {result['error']}",
            "sql": sql,
            "validation": result["validation"],
            # The generation call was still made (and paid for) even though the
            # SQL was blocked; the course version reported 0 here.
            "token_usage": token_usage,
        }

    # Step 7 fix: the course deployment prompt showed only question, columns and rows.
    # Without the SQL, Claude read the filtered client list as "the clients table" and
    # answered "there is no invoice data". It also used general knowledge to answer the
    # document half of "both" questions. The orchestrator-lab version included the SQL;
    # this restores it and keeps the answer to the rows.
    prompt = (
        f"Question: {question}\n"
        f"SQL that was run (its WHERE clause already applies the question's conditions): {sql}\n"
        f"Columns: {result['columns']}\n"
        f"Rows returned: {result['rows'][:20]}\n\n"
        "Answer the question using ONLY these rows. If part of the question cannot be "
        "answered from these rows, say so in one sentence and do not answer it from "
        "general knowledge. Answer concisely."
    )
    interpretation = invoke_claude(prompt, max_tokens=500, component="sql_interpretation")
    token_usage["sql_interpretation"] = {"input": interpretation["input_tokens"],
                                         "output": interpretation["output_tokens"],
                                         "cost_usd": interpretation["cost_usd"]}

    return {
        "answer": interpretation["text"],
        "sql": sql,
        "validation": result["validation"],
        "token_usage": token_usage,
    }


def run_sql_agent(question: str, history: list = None, confirmed_sql: str = None) -> dict:
    """Standardized wrapper matching the Shared Tool Registry lab's interface.
    `history` (Stretch A) and `confirmed_sql` (Stretch B) are optional; omitting
    them behaves exactly as before."""
    result = validated_sql_agent(question, history, confirmed_sql)
    metadata = {"validation": result["validation"], "token_usage": result["token_usage"]}
    if result["validation"] == "NEEDS_CONFIRMATION":
        metadata.update({"needs_confirmation": True, "reason": result["reason"], "sql": result["sql"]})
    return {
        "success": result["validation"] == "PASSED",
        "answer": result["answer"],
        "sources": [f"SQL: {result['sql']}"],
        "metadata": metadata,
    }