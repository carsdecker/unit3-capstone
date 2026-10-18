# Unit 3 Capstone: Multi-Agent System on AWS

A LangGraph orchestrator that answers questions about a consulting firm's operations by routing each
question to a **SQL Query Agent** (Amazon RDS PostgreSQL), a **Retrieval Agent** (Amazon OpenSearch
vector search), or both, then synthesising one cited answer. Claude Sonnet 4.6 is called through
**Amazon Bedrock**. Every generated SQL query passes a validator before it can reach the database. The
system is deployed as an **AWS Lambda** function.

**Tier: 🥇 Gold.** Bronze (Steps 1–8) + Stretch Goal A (conversation memory) + Stretch Goal B
(human-in-the-loop confirmation) + the combined Gold test, all verified locally **and** on Lambda.

---

## Architecture

```
Request → lambda_handler.handler(event)
            │  • body: {question, history?, confirm?}
            │  • confirm present → verify HMAC token (exact SQL + route) or 403 — trust boundary
            ▼
   tokenomics_logger.run_traced_query  ── [LOG] query_start / query_complete (trace_id)
            ▼
 ┌──────────────────── LangGraph StateGraph (orchestrator.py) ────────────────────┐
 │  router ──► sql_agent ──► retrieval_agent ──► synthesiser ──► END             │
 │  (Claude classifies       (skips itself      (skips itself    (merges results │
 │   using tool_registry      unless route is    unless route is   + every       │
 │   descriptions + history;  sql/both)          retrieval/both,   component's   │
 │   skipped for a signed                        or while paused)  token usage)  │
 │   confirmation)                                                               │
 └───────────────────────────────────────────────────────────────────────────────┘
        │                         │
        ▼                         ▼
 SQL Query Agent (agents/sql_agent.py)        Retrieval Agent (agents/retrieval_agent.py)
  generate_sql (Claude, + history)             onnx_embed (all-MiniLM-L6-v2 via ONNX Runtime)
  → validate_sql ──────── blocked? stop        → OpenSearch k-NN (top 5 chunks, innerproduct)
  → unusual_reason ────── flagged? pause       → cited answer (Claude) + grounding check
  → execute_query_safely (validator AGAIN,
       read-only session, 10 s timeout) → RDS
  → interpretation (Claude, rows only)
        │                         │
        └──── bedrock_client.invoke_claude: the ONLY path to Claude; logs every call
              "[CLAUDE CALL] component in/out cost" → CloudWatch + /tmp/claude_calls.jsonl
```

| File | Role |
|---|---|
| `lambda_handler.py` | Lambda entry point; carries `history`; issues and verifies confirmation tokens |
| `orchestrator.py` | LangGraph state graph: router → sql_agent → retrieval_agent → synthesiser |
| `tool_registry.py` | Both tools with "use for / do NOT use for" descriptions (they drive routing) |
| `agents/sql_agent.py` | NL→SQL, validator, review step, read-only execution, interpretation |
| `agents/retrieval_agent.py` | Embedding, OpenSearch search, cited answer, grounding check |
| `bedrock_client.py` | Claude via Bedrock; per-call token + USD logging (single choke point) |
| `tokenomics_logger.py` | Traced queries (course file, extended for history/confirmation) |
| `conversation.py` | Stretch A: history validation and the replay cap |
| `confirmation.py` | Stretch B: "unusual" criteria and HMAC sign/verify |
| `onnx_embed.py` | Embeddings without PyTorch (fits Lambda's 250 MB limit) |
| `ingest_documents.py` | S3 → Textract → chunk → embed → OpenSearch |
| `scripts/load_schema.py`, `data/schema.sql` | RDS schema + seed data |
| `cost_summary.py` | 10-query cost summary through the full orchestrator |
| `scripts/gold_lambda_demo.sh` | Gold conversation through `aws lambda invoke` (also the demo) |
| `infra/*.json` | IAM trust/inline policies, OpenSearch access policy |

---

## Setup

Built on an AWS WorkSpace (Ubuntu, Python 3.12.3, us-east-1) from the course's Deployment Patterns
solution files. Resource suffix: `cdecker`.

**Infrastructure** (commands follow the Deployment Patterns lesson; policy files are in `infra/`):
1. IAM role `orchestrator-lambda-role-cdecker`: trust `lambda.amazonaws.com`,
   `AWSLambdaBasicExecutionRole`, inline `bedrock:InvokeModel`.
2. OpenSearch `orchestrator-search-cdecker` (2.11, t3.small.search). The access policy allows the
   Lambda role **and the WorkSpace user** (the course policy only listed the role, which would have
   blocked ingesting and checking documents from the WorkSpace).
3. RDS PostgreSQL 16 `orchestrator-db-cdecker` (db.t3.micro, user `dbadmin`, db `bootcamp`), port 5432
   opened on its security group.
4. S3 bucket `doc-ingest-pipeline-cd` holding the four course PDFs.

**Local environment**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
curl -L -o model.onnx "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx"
curl -L -o tokenizer.json "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer.json"
```
`.env` (never committed; listed in `.gitignore`):
```
RDS_HOST=...  RDS_PORT=5432  RDS_DATABASE=bootcamp  RDS_USER=dbadmin  RDS_PASSWORD=...
OPENSEARCH_ENDPOINT=search-orchestrator-search-cdecker-....us-east-1.es.amazonaws.com
CONFIRMATION_SECRET=<64 hex chars from secrets.token_hex(32)>
```

**Data**
```bash
python scripts/load_schema.py     # clients 5, projects 6, consultants 6, invoices 7
python ingest_documents.py        # 4 PDFs → Textract → 8 chunks in the "documents" index
```

**Deployment** (Step 8): dependencies installed with `pip install -t ~/deployment-package`, pinned to
the tested versions with a constraints file; code + `model.onnx` + `tokenizer.json` copied in; trimmed to
**245.46 MB** unzipped; zipped (132 MB), uploaded to `s3://lambda-deploy-798555098734-cdecker/`;
`aws lambda create-function` with runtime `python3.12`, 512 MB, 120 s, environment variables read from
`.env` in a sub-shell (never typed on the command line).

## Usage

```bash
# Local
python -c "from lambda_handler import handler; import json; print(handler({'body': json.dumps({'question': 'How many active projects do we have?'})}, None))"

# Deployed
aws lambda invoke --function-name multi-agent-orchestrator --payload file://request.json \
  --cli-binary-format raw-in-base64-out --cli-read-timeout 150 response.json
```
Request body fields: `question` (required); `history` (Stretch A: send back the `history` from the
previous response); `confirm` (Stretch B: send back the `confirm` block from a flagged response,
unchanged, with the same question). Response: `answer`, `route`, `sql_validation`, `sql`,
`token_usage` (per component + total), `history`, `needs_confirmation` (+ `reason`, `confirm` when
true).

---

## Evidence by requirement

Evidence files are in `evidence/`.

### 🥉 Bronze

| Step | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | RDS reachable + populated | clients 5, projects 6, consultants 6, invoices 7 | `step1_foundation.txt` |
| 1 | OpenSearch reachable + populated | 8 chunks; stipend question → remote-work-policy.pdf | `step1_foundation.txt` |
| 2 | One interface | both tools return exactly `answer, metadata, sources, success` | `step2_interface.txt` |
| 3 | Registry with specific descriptions | each says what it is for **and** not for, written for our data | `step3_registry.txt` |
| 4 | Single-tool routing | `sql` / `retrieval`, the other agent's result is `None` | `step4_orchestrator.txt` |
| 4 | Multi-tool routing + synthesis | `both`, both results present, answer credits SQL Agent and Retrieval Agent | `step4_orchestrator.txt` |
| 5 | No path skips the validator | tripwire tests + `psycopg2.connect` only in `execute_query_safely` | `step5_no_bypass.txt` |
| 5 | Blocks unsafe SQL (5+ cases) | all 5 required cases + 9 more pass (14 tests) | `step5_validator.txt` |
| 6 | Every Claude call logged | 5 calls with tokens + USD, matching the state total | `step6_tokenomics_calls.txt` |
| 6 | 10-query cost summary | **$0.108810** total; `retrieval_answer` most tokens and cost | `step6_cost_summary_10_queries.txt` |
| 7 | 8 test questions documented | 8/8; unsafe **BLOCKED**, unanswerable declined | `step7_questions_run3.txt` (+ runs 1–2) |
| 8 | Deployed + invoked | `route: both`, `sql_validation: PASSED`, attributed answer, non-zero tokens, CloudWatch lines | `step8_lambda_deployment.txt`, `step8_response.json` |

### 🥈 Stretch Goal A — conversation memory

| Requirement | Result | Evidence |
|---|---|---|
| Follow-ups resolve | "What about their total contract value?" → `WHERE c.name = 'Acme Corp'` → **$250,000** (a no-memory control fell back to all clients) | `stretchA_two_turn_local.txt` |
| Works deployed | same two-turn exchange through `aws lambda invoke`, history copied from response 1 | `stretchA_lambda_two_turn.txt` |
| Cost measured | **+133 input tokens** each to classification and SQL generation per replayed turn | `stretchA_two_turn_local.txt` |

**The cap:** replay at most the **last 3 turns**, each answer cut to **400 characters**
(`conversation.py`). Follow-ups almost always refer to the last turn or two. Synthesised answers run to
~1,500 characters, but the subject a follow-up needs is stated in the first sentences. Every replayed
turn is re-sent to two prompts on every later question, so an uncapped history would grow cost without
limit.

### 🥈 Stretch Goal B — human-in-the-loop confirmation

**"Unusual"** (`confirmation.unusual_reason`): a query that **joins more than two tables**, or that
**returns raw rows from a whole table** (no `WHERE`, no `LIMIT`, no aggregate).

**Exactness:** the handler returns the flagged SQL with an **HMAC-SHA256 token** over `{sql, route}`,
signed with `CONFIRMATION_SECRET`. A confirmation is accepted only if the SQL and route re-sign to the
same token, so changing a single character is rejected (403). This is stateless, which suits Lambda,
and reliable, unlike regenerating the SQL (Claude's SQL differs from run to run). A confirmed query
skips generation and review but **always** passes through the validator.

| Requirement | Result | Evidence |
|---|---|---|
| Unusual queries pause | `SELECT * FROM invoices` → SQL, reason, `needs_confirmation: true`, nothing executed | `stretchB_gold_local_live.txt`, `stretchB_flow_free.txt` |
| Only the flagged query runs | exact → PASSED with identical SQL; altered → **403** | `stretchB_gold_local_live.txt` |
| Normal queries unaffected | `COUNT(*) ... WHERE status = 'active'` runs straight through | `stretchB_gold_local_live.txt` |
| Validation still applies | a correctly signed `DROP TABLE invoices` → **BLOCKED** | `stretchB_flow_free.txt` |

### 🥇 Gold — together and deployed

| Requirement | Result | Evidence |
|---|---|---|
| Memory + confirmation coexist | turn 2 "every invoice for **their** projects" → `WHERE c.name = 'Acme Corp'` → flagged (3 tables) → confirmed → **identical query executed** | `stretchB_gold_local_live.txt` |
| Both deployed | same through `aws lambda invoke`; Acme's token reused for Beta Financial → 403, rejected in **2 ms** before any Claude call | `gold_lambda.txt`, `gold_lambda/` |

---

## What testing found (Trust but Verify)

Each of these was found by a test or a log, not by reading the code, and each fix was re-tested.

| Found | How | Fix |
|---|---|---|
| Course keyword router misrouted **3 of 9** questions ("what is" → both; "how much" → SQL for a policy question) | `test_routing.py` | Claude classifies using the registry descriptions → **15/15**, including 6 held-out questions written after the change |
| `SELECT * INTO clients_copy FROM clients` **passed** the validator, though it creates a table | "try to break your validator" tests | `INTO` blocked; **plus** a database backstop (read-only session + 10 s timeout) proven with the validator switched off |
| The state's `token_usage` reported **only synthesis**: about 11% of the input tokens of a `both` question | Step 4 output | Every call labelled at `bedrock_client`; components merged and totalled; SQL generation (previously discarded) counted |
| "Which client has overdue invoices?" answered "there is no invoice data" | Step 7 run 1 | Interpretation prompt now includes the SQL; invoice statuses documented in the schema context |
| The SQL agent answered the **document** half of a `both` question from general knowledge | Step 7 run 1 | Interpretation limited to the returned rows |
| Synthesis linked the Q2 report's "48% spend" to a project the report never names | Step 7 runs 1–2 | Synthesis rule: only connect facts when a source states the connection |
| A blocked query told the user "unable to find relevant information" | Step 7 | Users are told the request was blocked, and why |
| The course's package trim list deletes `websockets` and `langchain_protocol`, which these library versions import at start-up | import-blocking simulation before deploying | Kept both; deleted `google`/`grpc` (43 MB) instead |
| The course's packaging list omitted `tool_registry.py`, which our router imports | review before packaging | Bundled; isolated package test passed before upload |
| The retrieval agent never loaded `.env` (it only worked because the SQL agent was imported first) | testing the tool on its own | `load_dotenv()` added |

---

## Tokenomics

Pricing: Claude Sonnet 4.6 on Bedrock, **$3.00 / 1M input** and **$15.00 / 1M output** tokens
(screenshot `evidence/bedrock_pricing_2026-10-16.png`; the page shows no separate price for the `us.`
cross-region profile used, so it is assumed equal).

**10 queries through the full orchestrator: $0.108810** (24,082 tokens), averaging **$0.0109 per
query** (about $10.88 per 1,000).

| Component | Calls | Tokens | Cost share |
|---|---|---|---|
| retrieval_answer | 6 | 14,362 (60%) | **49%**: mostly input, 5 chunks per call |
| synthesis | 9 | 4,154 | **31%**: 59% of all output tokens |
| classification | 10 | 3,320 | 10% |
| sql_generation | 6 | 1,413 | 6% |
| sql_interpretation | 5 | 833 | 4% |

- **By route:** sql $0.0036–0.0046 · retrieval $0.0108–0.0160 · both $0.0180–0.0224 · blocked $0.0019.
- Synthesis on single-tool questions cost **18.5%** of the total, spent reformatting finished answers.
- Memory adds +57 input tokens to every query (the instruction line), plus about 133 tokens per
  replayed turn to each of two prompts.
- A confirmation skips classification and generation, so it is cheaper than asking afresh. But confirming
  a whole-table dump was the costliest answer step seen ($0.0147), which makes the pause a cost
  checkpoint as well as a safety one.

---

## Testing

All tests are **pytest with assertions**. Tests that call Claude carry the `live` marker (`pytest.ini`).

```bash
python -m pytest -m "not live" -q     # free: no Claude calls (RDS/OpenSearch tests use the real services)
python -m pytest -m live -v -s        # integration tests with real Claude (a few cents)
```

| Test file | Covers | Cost |
|---|---|---|
| `test_foundation.py` | Step 1: RDS rows, OpenSearch count, retrieval sanity | free |
| `test_validator.py` | Step 5: 5 required cases + edge and attack cases | free |
| `test_db_backstop.py` | read-only + timeout enforced by PostgreSQL itself | free |
| `test_no_bypass.py` | no path to the database skips the validator | free |
| `test_registry.py` | Step 3 descriptions; unknown tool fails safely | free |
| `test_memory.py`, `test_confirmation.py`, `test_confirmation_flow.py` | Stretch A/B logic and the full handler loop with Claude faked | free |
| `test_interface.py`, `test_routing.py`, `test_orchestrator.py`, `test_tokenomics.py`, `test_step7_questions.py`, `test_lambda_handler.py`, `test_memory_live.py`, `test_confirmation_live.py` | integration tests across agents, orchestrator and handler | live |

---

## Design decisions and departures from the course code

1. **Claude-based routing** using the registry descriptions, replacing the keyword router (evidence above).
2. **Validator:** `INTO` added; a database-level read-only + timeout backstop added.
3. **Token accounting:** per-call logging at `bedrock_client`; SQL generation counted; components merged.
4. **SQL interpretation** sees the SQL and answers only from the returned rows; invoice statuses documented.
5. **Synthesis:** reports blocked, failed or paused SQL honestly; doesn't connect facts across sources unless a source does.
6. **Ingestion** uses `onnx_embed` (the same code as query time) and `innerproduct` (faiss doesn't support `cosinesimil`).
7. **Packaging:** versions pinned to the tested set; corrected trim list; `tool_registry.py`, `conversation.py` and `confirmation.py` bundled.
8. **OpenSearch access policy** includes the WorkSpace user as well as the Lambda role.

## Known limitations

- **Security:** the RDS master password is weak and was not rotated; port 5432 is open to `0.0.0.0/0`
  (needed for Lambda outside a VPC); the password is a plain Lambda environment variable. Production
  would use a VPC, AWS Secrets Manager and a rotated strong password.
- **Confirmation tokens do not expire** and can be replayed for the same (read-only, approved) query.
  Only explicit `JOIN`s are counted (not comma joins or subqueries). Because the threshold is "more than
  two tables", *"Which client has overdue invoices?"* (3 tables) now pauses for confirmation.
- **Memory** reaches the classifier and SQL generation only (as the brief specifies), so document
  follow-ups like "what's the deadline for that?" are not resolved.
- **Retrieval** always sends the top 5 of 8 chunks, mostly irrelevant ones (60% of all tokens). The
  500-word chunks exceed the embedding model's 256-token window, so their tails are not embedded.
- **NL→SQL varies** between runs (the same question has produced different but valid SQL).
- **Naming overlap:** the firm is "Acme Consulting" (documents) while "Acme Corp" is a client (database).
- **Lambda memory:** `both` questions use about 450 of 512 MB (the ONNX model loads only when retrieval runs).

---

## Reflection

The question that most tested my orchestrator was *"What was the budget of our completed Data Migration
project, and what does our migration playbook say should happen before final cutover?"* Routing and
validation both worked: it went to both agents, and the SQL was valid and correct ($90,000). The failure
was in **synthesis**, made worse by how the work was handed out. Each agent received the whole question,
so the SQL agent answered the playbook half from general knowledge. The synthesiser then presented those
invented steps as what "our playbook says", and it also linked the Q2 report's "48% spend" to a project
the report never names. Every automated check passed. The SQL was valid, the citations existed, and the
route was right. This shows where multi-agent systems are still fragile compared with one well-scoped
agent: at the **hand-offs**. Each agent can be individually correct while the combination asserts
something no source supports, and checks that look at one component at a time can't see it. Fixing it
took rules at the seams (agents answer only from their own data; synthesis connects sources only when a
source does), and the sure way to catch it was reading the answer against the answer key.

---

## Teardown (after evaluation only)

```bash
./teardown.sh --name cdecker            # dry run
./teardown.sh --name cdecker --confirm  # deletes the Lambda, RDS, OpenSearch and deployment bucket
aws s3 rm s3://doc-ingest-pipeline-cd --recursive && aws s3 rb s3://doc-ingest-pipeline-cd   # teardown.sh doesn't match this name
```
The IAM role cannot be deleted in this sandbox (IAM is free).
