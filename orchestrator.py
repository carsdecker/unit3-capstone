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
from dotenv import load_dotenv
load_dotenv()


class OrchestratorState(TypedDict):
    question: str
    route: Optional[str]            # "sql", "retrieval", or "both"
    sql_result: Optional[dict]
    retrieval_result: Optional[dict]
    final_answer: Optional[str]
    token_usage: Optional[dict]


# Classification node: Claude routes using the tool registry's descriptions.
# Replaced the course's keyword router after tests/test_routing.py showed it
# misrouting 3 of 9 questions ("what is" sent SQL questions to "both"; "how much"
# sent the home-office stipend question to SQL) -- keywords match words, not
# meaning. Evidence: evidence/routing_keyword_baseline.txt.
ROUTER_PROMPT = """You route questions for a consulting firm's assistant to the right data source.

Available tools:
{tools}

Reply with exactly one word:
sql - only the database is needed
retrieval - only the documents are needed
both - the question needs information from the database AND the documents
If neither source could answer the question, reply retrieval (the documents agent will say it cannot find it).

Question: {question}"""

VALID_ROUTES = {"sql", "retrieval", "both"}


def route_question(state: OrchestratorState) -> OrchestratorState:
    # The descriptions come straight from tool_registry.py, so editing a
    # description there changes routing here -- one source of truth.
    tools = "\n".join(f"- {s['name']}: {s['description']}" for s in get_all_schemas())
    result = invoke_claude(ROUTER_PROMPT.format(tools=tools, question=state["question"]), max_tokens=5)

    # Normalise the reply: Claude may add a capital letter or a full stop.
    route = result["text"].strip().lower().strip(".")
    if route not in VALID_ROUTES:
        # An unexpected reply runs both agents rather than guessing one: slower and
        # dearer, but the question still gets answered, and SQL is still validated.
        route = "both"

    usage = {"input": result["input_tokens"], "output": result["output_tokens"]}
    # NOTE (Step 6): synthesise() currently overwrites token_usage, so this is lost
    # by the end of the graph. Step 6 merges every component's usage.
    return {**state, "route": route, "token_usage": {"classification": usage}}


def call_sql_agent(state: OrchestratorState) -> OrchestratorState:
    if state["route"] not in ["sql", "both"]:
        return state            # not needed for this route: skip without calling the agent
    result = run_sql_agent(state["question"])
    return {**state, "sql_result": result}


def call_retrieval_agent(state: OrchestratorState) -> OrchestratorState:
    if state["route"] not in ["retrieval", "both"]:
        return state
    result = run_retrieval_agent(state["question"])
    return {**state, "retrieval_result": result}


def synthesise(state: OrchestratorState) -> OrchestratorState:
    context = ""

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
            "token_usage": {"input": 0, "output": 0}
        }

    prompt = (
        f"Using the information below, answer the following question clearly.\n"
        f"Cite which agent(s) and source(s) the information came from.\n\n"
        f"Question: {state['question']}\n\n"
        f"Information:\n{context}"
    )
    result = invoke_claude(prompt, max_tokens=800)

    return {
        **state,
        "final_answer": result["text"],
        # NOTE (Step 6): only this synthesis call's tokens -- the agents' tokens are not added.
        "token_usage": {
            "input": result["input_tokens"],
            "output": result["output_tokens"]
        }
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