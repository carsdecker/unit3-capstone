# cost_summary.py — Brief Step 6: cost summary from 10 queries through the full orchestrator.
# Uses run_traced_query, the same path lambda_handler.py uses in production.
# LIVE: about 35 Claude calls (roughly 11 cents).
from collections import defaultdict
from orchestrator import orchestrator
from tokenomics_logger import run_traced_query

QUESTIONS = [
    "How many active projects do we have?",
    "Which client has overdue invoices?",
    "How much can employees claim for home office equipment?",
    "What are common pitfalls in a cloud data migration?",
    "How many active projects do we have, and what are the core hours in our remote work policy?",
    "What was the budget of our completed Data Migration project, and what does our migration "
    "playbook say should happen before final cutover?",
    "Delete all overdue invoices from the database.",
    "What is our CEO's favourite colour?",
    "Which consultant has logged the most billable hours?",
    "What results did the grocery client see after the forecasting rollout?",
]

components = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0, "cost_usd": 0.0})
rows = []

for question in QUESTIONS:
    state = run_traced_query(orchestrator, question)
    usage = state["token_usage"]
    for name, u in usage.items():
        if name == "total":
            continue
        c = components[name]
        c["calls"] += 1
        c["input"] += u["input"]
        c["output"] += u["output"]
        c["cost_usd"] += u["cost_usd"]
    rows.append((question, state["route"], usage["total"]))

grand_cost = sum(t["cost_usd"] for _, _, t in rows)
grand_tokens = sum(t["input"] + t["output"] for _, _, t in rows)

print("\n" + "=" * 100)
print("PER QUERY")
print(f"{'#':<3}{'route':<11}{'input':>7}{'output':>8}{'cost_usd':>11}  question")
for i, (q, route, t) in enumerate(rows, 1):
    print(f"{i:<3}{route:<11}{t['input']:>7}{t['output']:>8}{t['cost_usd']:>11.6f}  {q[:60]}")

print("\nPER COMPONENT")
print(f"{'component':<20}{'calls':>6}{'input':>8}{'output':>8}{'tokens':>8}{'cost_usd':>11}{'% cost':>8}")
for name, c in sorted(components.items(), key=lambda kv: -kv[1]["cost_usd"]):
    tokens = c["input"] + c["output"]
    print(f"{name:<20}{c['calls']:>6}{c['input']:>8}{c['output']:>8}{tokens:>8}"
          f"{c['cost_usd']:>11.6f}{c['cost_usd'] / grand_cost:>8.0%}")

most_tokens = max(components, key=lambda n: components[n]["input"] + components[n]["output"])
most_cost = max(components, key=lambda n: components[n]["cost_usd"])
print(f"\nQueries: {len(rows)} | Total tokens: {grand_tokens:,} | TOTAL COST: ${grand_cost:.6f}")
print(f"Average per query: ${grand_cost / len(rows):.6f} (~${grand_cost / len(rows) * 1000:.2f} per 1,000 queries)")
print(f"Most tokens: {most_tokens} | Most cost: {most_cost}")