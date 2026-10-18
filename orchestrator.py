"""
orchestrator.py -- routes a question to the SQL agent, the retrieval agent,
or both, then synthesizes a single cited answer.
(Based on the course file from Deployment Patterns on AWS.)
"""
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional
from bedrock_client import invoke_claude
from agents.sql_agent import run_sql_agent
from agents.retrieval_agent import run_retrieval_agent
from tool_registry import get_all_schemas
from conversation import format_history
from dotenv import load_dotenv
load_dotenv()


class OrchestratorState(TypedDict):
    question: str
    route: Optional[str]            # "sql", "retrieval", or "both"
    sql_result: Optional[dict]
    retrieval_result: Optional[dict]
    final_answer: Optional[str]
    token_usage: Optional[dict]     # per component + "total" (see add_total)
    history: Optional[list]         # Stretch Goal A: prior {question, answer} turns
    confirmed_sql: Optional[str]    # Stretch Goal B: an exact, already-verified query to run


# Classification node: Claude routes using the tool registry's descriptions.
# Replaced the course's keyword router after tests/test_routing.py showed it
# misrouting 3 of 9 questions ("what is" sent SQL questions to "both"; "how much"
# sent the home-office stipend question to SQL) -- keywords match words, not
# meaning. Evidence: evidence/routing_keyword_baseline.txt.
# Stretch Goal A: {history} lets a follow-up ("What about their contract value?")
# be routed by what it refers to, not just its own words.
ROUTER_PROMPT = """You route questions for a consulting firm's assistant to the right data source.

Available tools:
{tools}

Reply with exactly one word:
sql - only the database is needed
retrieval - only the documents are needed
both - the question needs information from the database AND the documents
If neither source could answer the question, reply retrieval (the documents agent will say it cannot find it).
If the question refers to the conversation (e.g. "their", "that project"), use the conversation to decide.

{history}Question: {question}"""

VALID_ROUTES = {"sql", "retrieval", "both"}


def route_question(state: OrchestratorState) -> OrchestratorState:
    if state.get("confirmed_sql") and state.get("route") in VALID_ROUTES:
        # Stretch Goal B: a confirmation carries the route that was signed with the
        # query, so it is not re-classified (re-classifying could pick another route).
        return {**state, "token_usage": {}}

    # The descriptions come straight from tool_registry.py, so editing a
    # description there changes routing here -- one source of truth.
    tools = "\n".join(f"- {s['name']}: {s['description']}" for s in get_all_schemas())
    prompt = ROUTER_PROMPT.format(tools=tools, history=format_history(state.get("history")),
                                  question=state["question"])
    result = invoke_claude(prompt, max_tokens=5, component="classification")

    # Normalise the reply: Claude may add a capital letter or a full stop.
    route = result["text"].strip().lower().strip(".")
    if route not in VALID_ROUTES:
        # An unexpected reply runs both agents rather than guessing one: slower and
        # dearer, but the question still gets answered, and SQL is still validated.
        route = "both"

    usage = {"input": result["input_tokens"], "output": result["output_tokens"],
             "cost_usd": result["cost_usd"]}
    return {**state, "route": route, "token_usage": {"classification": usage}}


def call_sql_agent(state: OrchestratorState) -> OrchestratorState:
    if state["route"] not in ["sql", "both"]:
        return state            # not needed for this route: skip without calling the agent
    result = run_sql_agent(state["question"], state.get("history"), state.get("confirmed_sql"))
    return {**state, "sql_result": result}


def call_retrieval_agent(state: OrchestratorState) -> OrchestratorState:
    if state["route"] not in ["retrieval", "both"]:
        return state
    if (state.get("sql_result") or {}).get("metadata", {}).get("needs_confirmation"):
        # Stretch Goal B: the request is paused; the documents half runs after
        # confirmation, so don't pay for it twice.
        return state
    result = run_retrieval_agent(state["question"])
    return {**state, "retrieval_result": result}


def add_total(usage: dict) -> dict:
    # Sum every component into a "total" entry (the Lambda response's token_usage).
    parts = [v for k, v in usage.items() if k != "total"]
    usage["total"] = {
        "input": sum(p["input"] for p in parts),
        "output": sum(p["output"] for p in parts),
        "cost_usd": round(sum(p["cost_usd"] for p in parts), 6),
    }
    return usage


def synthesise(state: OrchestratorState) -> OrchestratorState:
    # Step 6 fix: the course version replaced token_usage with the synthesis call's
    # tokens alone, hiding classification and both agents. Merge every component.
    usage = dict(state.get("token_usage") or {})
    for key in ("sql_result", "retrieval_result"):
        if state.get(key):
            usage.update(state[key]["metadata"].get("token_usage", {}))

    sql_meta = (state.get("sql_result") or {}).get("metadata", {})
    if sql_meta.get("needs_confirmation"):
        # Stretch Goal B: paused for a person. State it plainly; no synthesis call.
        return {**state,
                "final_answer": (f"This query needs your confirmation before it runs, because "
                                 f"{sql_meta['reason']}. Nothing has been executed. "
                                 f"SQL: {sql_meta['sql']}"),
                "token_usage": add_total(usage)}

    context = ""

    # Step 7 fix: a blocked or failed SQL agent used to vanish silently, so
    # "Delete all overdue invoices" answered "I was unable to find relevant
    # information" -- hiding that the validator had refused it. Say what happened.
    sql_note = ""
    if state.get("sql_result") and not state["sql_result"].get("success"):
        if state["sql_result"]["metadata"].get("validation") == "BLOCKED":
            # Stretch A finding: the first version always said "only runs read-only
            # queries", but a block can also mean Claude returned prose instead of SQL
            # (seen in the no-memory control). Report the validator's actual reason.
            reason = state["sql_result"]["answer"].removeprefix("Query blocked or failed: ")
            sql_note = ("The database part of this request was blocked by the SQL safety check "
                        f"({reason}), so the generated SQL was not executed.")
        else:
            sql_note = "The database query could not be completed, so no database results are available."
        context += f"SQL Agent Result:\n{sql_note}\n\n"

    if state.get("sql_result") and state["sql_result"].get("success"):
        r = state["sql_result"]
        context += f"SQL Agent Result:\n{r['answer']}\nSources: {r['sources']}\n\n"

    if state.get("retrieval_result") and state["retrieval_result"].get("success"):
        r = state["retrieval_result"]
        context += f"Retrieval Agent Result:\n{r['answer']}\nSources: {r['sources']}\n\n"

    if not context:
        return {
            **state,
            "final_answer": "I was unable to find relevant information to answer this question.",
            # Earlier calls were still made and paid for, so keep their usage.
            "token_usage": add_total(usage),
        }

    if sql_note and not state.get("retrieval_result"):
        # SQL-only question that was blocked or failed: nothing for Claude to
        # synthesise, so state the outcome directly (no extra Claude call).
        return {**state, "final_answer": sql_note, "token_usage": add_total(usage)}

    # Step 7 fix: "Only connect facts..." added after the Data Migration question's
    # answer compared the project's $90,000 budget with the Q2 report's "48% spend",
    # although the report never names that project -- an unsupported cross-source link.
    prompt = (
        f"Using the information below, answer the following question clearly.\n"
        f"Cite which agent(s) and source(s) the information came from.\n"
        f"Only connect facts from different sources if one of the sources states that "
        f"connection; otherwise present them separately.\n\n"
        f"Question: {state['question']}\n\n"
        f"Information:\n{context}"
    )
    result = invoke_claude(prompt, max_tokens=800, component="synthesis")
    usage["synthesis"] = {"input": result["input_tokens"], "output": result["output_tokens"],
                          "cost_usd": result["cost_usd"]}

    return {
        **state,
        "final_answer": result["text"],
        "token_usage": add_total(usage),
    }


def build_orchestrator():
    graph = StateGraph(OrchestratorState)
    graph.add_node("router", route_question)
    graph.add_node("sql_agent", call_sql_agent)
    graph.add_node("retrieval_agent", call_retrieval_agent)
    graph.add_node("synthesiser", synthesise)

    graph.set_entry_point("router")
    graph.add_edge("router", "sql_agent")
    graph.add_edge("sql_agent", "retrieval_agent")
    graph.add_edge("retrieval_agent", "synthesiser")
    graph.add_edge("synthesiser", END)

    return graph.compile()


orchestrator = build_orchestrator()