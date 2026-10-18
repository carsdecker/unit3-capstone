"""
conversation.py -- Stretch Goal A: conversation memory helpers.

Lambda keeps no memory between invocations, so the CALLER sends the prior turns
as `history` and receives the updated history back. Only the most recent turns
are replayed into prompts, because every replayed turn adds input tokens to every
later Claude call that receives it (classification and SQL generation).
"""

# THE CAP: replay at most the last 3 turns, each answer cut to 400 characters.
# Why 3 turns: follow-ups almost always refer to the last turn or two ("their",
# "that project"); a third gives margin for a slightly older reference.
# Why 400 characters: synthesised answers run to ~1,500 characters of markdown
# (300+ tokens), while the subject a follow-up needs ("Acme Corp has 1 active
# project") is stated in the first sentences. The measured cost is recorded in
# the Stretch Goal A evidence.
MAX_TURNS = 3
MAX_ANSWER_CHARS = 400


def trim_history(history) -> list:
    # history arrives from the caller (the Lambda request), so treat it as untrusted:
    # keep only well-formed {question, answer} turns, then keep the most recent ones.
    if not isinstance(history, list):
        return []
    turns = [t for t in history
             if isinstance(t, dict) and isinstance(t.get("question"), str)
             and isinstance(t.get("answer"), str)]
    return turns[-MAX_TURNS:]


def format_history(history) -> str:
    turns = trim_history(history)
    if not turns:
        return ""
    lines = [f"User: {t['question']}\nAssistant: {t['answer'][:MAX_ANSWER_CHARS]}" for t in turns]
    return "Conversation so far (most recent last):\n" + "\n\n".join(lines) + "\n\n"