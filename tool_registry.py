# tool_registry.py — Brief Step 3: one registry for both tools.
# Structure follows the course's Shared Tool Registry lab. The descriptions are
# rewritten to match THIS project's actual data: the course version promised
# "onboarding, expense guidelines", which none of our documents contain, and a
# description that over-promises sends questions to the wrong tool.
from agents.sql_agent import run_sql_agent
from agents.retrieval_agent import run_retrieval_agent

TOOL_REGISTRY = {
    "sql_agent": {
        "function": run_sql_agent,
        "schema": {
            "name": "sql_agent",
            "description": (
                "Use for questions answered by the firm's live relational database: client "
                "companies (name, industry, region, contract value), projects (status, budget, "
                "dates), consultants (grade, specialisation, billable hours) and invoices "
                "(amount, paid/pending/overdue). Use for counts, totals, averages, filters "
                "and comparisons across those records. "
                "Do NOT use for policies, procedures, methodology, or any figure quoted inside "
                "a document such as a client report or case study."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    "retrieval_agent": {
        "function": run_retrieval_agent,
        "schema": {
            "name": "retrieval_agent",
            "description": (
                "Use for questions answered by the firm's written documents: the remote work "
                "policy (eligibility, core hours, equipment, home office stipend), the cloud "
                "migration playbook (phases, strategies, pitfalls), the Q2 2026 client "
                "engagement report (milestones, risks, budget status, staffing), and the retail "
                "supply chain case study (approach and results), including any figures quoted "
                "in them. "
                "Do NOT use for counts, totals or lookups of clients, projects, consultants or "
                "invoices stored in the database."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
}


def get_all_schemas() -> list:
    return [tool["schema"] for tool in TOOL_REGISTRY.values()]


def call_tool(tool_name: str, question: str) -> dict:
    # An unknown name returns the standard shape instead of crashing, so a bad
    # routing decision fails safely.
    if tool_name not in TOOL_REGISTRY:
        return {"success": False, "answer": f"Unknown tool: {tool_name}", "sources": [], "metadata": {}}
    return TOOL_REGISTRY[tool_name]["function"](question)