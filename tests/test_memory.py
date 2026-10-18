# tests/test_memory.py — Stretch Goal A: conversation memory plumbing.
# FREE: invoke_claude is replaced by a fake that records the prompt it was sent.
from agents import sql_agent
import orchestrator
from conversation import trim_history, format_history, MAX_TURNS, MAX_ANSWER_CHARS

ACME_TURN = {"question": "How many active projects does Acme Corp have?",
             "answer": "Acme Corp has 1 active project: Client Portal Redesign."}


def recording_fake(captured: dict, reply: str):
    def fake(prompt, max_tokens=500, component="unlabelled"):
        captured["prompt"] = prompt
        return {"text": reply, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    return fake


# ---- The cap (brief step 4) ------------------------------------------------

def test_only_the_last_turns_are_kept():
    history = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(5)]
    kept = trim_history(history)
    assert len(kept) == MAX_TURNS
    assert [t["question"] for t in kept] == ["q2", "q3", "q4"]   # the most recent three


def test_long_answers_are_cut():
    text = format_history([{"question": "q", "answer": "x" * 2000}])
    assert "x" * MAX_ANSWER_CHARS in text
    assert "x" * (MAX_ANSWER_CHARS + 1) not in text


def test_malformed_history_is_ignored_not_crashing():
    # history comes from whoever calls the Lambda, so it can't be trusted
    assert trim_history("not a list") == []
    assert trim_history([{"question": 1}, "junk", ACME_TURN]) == [ACME_TURN]


# ---- History reaches the prompts (brief step 2) ------------------------------

def test_sql_generation_prompt_includes_history(monkeypatch):
    captured = {}
    monkeypatch.setattr(sql_agent, "invoke_claude", recording_fake(captured, "SELECT 1"))
    sql_agent.generate_sql("What about their total contract value?", [ACME_TURN])
    print(f"\n  SQL generation prompt (start):\n{captured['prompt'][:600]}")
    assert "Acme Corp" in captured["prompt"]
    assert "Conversation so far" in captured["prompt"]


def test_classifier_prompt_includes_history(monkeypatch):
    captured = {}
    monkeypatch.setattr(orchestrator, "invoke_claude", recording_fake(captured, "sql"))
    state = {"question": "What about their total contract value?", "history": [ACME_TURN]}
    orchestrator.route_question(state)
    assert "Acme Corp" in captured["prompt"]
    assert "Conversation so far" in captured["prompt"]


def test_without_history_the_prompts_are_unchanged(monkeypatch):
    # No history -> no conversation block, so single questions cost exactly what they did.
    captured = {}
    monkeypatch.setattr(sql_agent, "invoke_claude", recording_fake(captured, "SELECT 1"))
    sql_agent.generate_sql("How many active projects do we have?")
    assert "Conversation so far" not in captured["prompt"]


def test_only_capped_turns_reach_the_prompt(monkeypatch):
    captured = {}
    monkeypatch.setattr(sql_agent, "invoke_claude", recording_fake(captured, "SELECT 1"))
    history = [{"question": f"old question {i}", "answer": "a"} for i in range(5)]
    sql_agent.generate_sql("follow-up", history)
    assert "old question 0" not in captured["prompt"]    # dropped by the cap
    assert "old question 4" in captured["prompt"]        # most recent kept