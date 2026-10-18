"""
confirmation.py -- Stretch Goal B: human-in-the-loop confirmation.

1. unusual_reason(sql): decides whether a query that PASSED validation is still
   unusual enough that a person should approve it before it runs.
2. sign / verify: a stateless guarantee that a confirmation can only run the
   EXACT query that was flagged. Lambda keeps no memory between requests, so
   instead of storing the flagged query, the server signs it with a secret
   (HMAC-SHA256) and hands the signature back as a token. A confirmation must
   return the same SQL + route + token; changing even one character of the SQL
   makes the signature check fail. The validator still runs on a confirmed query.
"""
import hashlib
import hmac
import json
import os
import re
from dotenv import load_dotenv
load_dotenv()   # lesson from retrieval_agent: don't rely on another module loading .env

AGGREGATE = re.compile(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(", re.IGNORECASE)


def unusual_reason(sql: str):
    """Return why a query needs confirmation, or None if it is routine.

    Criteria (from the brief's examples):
      - joins more than two tables: wide joins can be slow and return far more
        rows than the question needs;
      - returns raw rows from a whole table: no WHERE, no LIMIT and no aggregate,
        i.e. a full table dump (aggregates like SUM over a table return one row,
        so they are routine).
    Limitation: only explicit JOINs are counted, not comma-style "FROM a, b".
    """
    upper = " ".join(sql.split()).upper()          # normalise whitespace and case
    joins = len(re.findall(r"\bJOIN\b", upper))
    if joins >= 2:
        return f"it joins {joins + 1} tables (more than two)"
    if (not re.search(r"\bWHERE\b", upper) and not re.search(r"\bLIMIT\b", upper)
            and not AGGREGATE.search(upper) and "GROUP BY" not in upper):
        return "it returns rows from a whole table: no WHERE, no LIMIT and no aggregate"
    return None


def _secret() -> bytes:
    secret = os.getenv("CONFIRMATION_SECRET")
    if not secret:
        # Fail closed: without a key no token can be issued or trusted.
        raise RuntimeError("CONFIRMATION_SECRET is not set")
    return secret.encode()


def sign(sql: str, route: str) -> str:
    # The route is signed too, so a confirmation can't switch which agents run.
    payload = json.dumps({"sql": sql, "route": route}, sort_keys=True).encode()
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def verify(sql: str, route: str, token) -> bool:
    # compare_digest takes the same time whether the first or last character
    # differs, so the timing of the check can't leak how much of a token is right.
    return isinstance(token, str) and hmac.compare_digest(sign(sql, route), token)