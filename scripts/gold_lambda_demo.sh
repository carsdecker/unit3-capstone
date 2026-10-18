#!/usr/bin/env bash
# scripts/gold_lambda_demo.sh — Gold evidence (and the live demo): conversation memory and
# human-in-the-loop confirmation working together, through `aws lambda invoke`.
# Each request is BUILT FROM THE PREVIOUS RESPONSE: the history and the signed confirm block
# are copied programmatically, never retyped. Requests/responses are saved in evidence/gold_lambda/.
# Run from the project root:  bash scripts/gold_lambda_demo.sh
set -euo pipefail
FN=multi-agent-orchestrator
DIR=evidence/gold_lambda
Q1="How many active projects does Acme Corp have?"
Q2="Show me every invoice for their projects, with the project names."
mkdir -p "$DIR"

invoke() {   # $1 = request file, $2 = response file
  aws lambda invoke --function-name "$FN" --payload "file://$1" \
    --cli-binary-format raw-in-base64-out --cli-read-timeout 150 "$2" > /dev/null
}

summary() {  # $1 = label, $2 = response file
  python3 - "$1" "$2" <<'EOF'
import json, sys
label, path = sys.argv[1], sys.argv[2]
outer = json.load(open(path))
body = json.loads(outer["body"])
print(f"\n=== {label} === statusCode {outer['statusCode']}")
for key in ("route", "sql_validation", "needs_confirmation", "reason", "sql", "error"):
    if key in body:
        print(f"  {key}: {body[key]}")
if "answer" in body:
    print(f"  answer: {body['answer'][:220]}")
if "history" in body:
    print(f"  history length: {len(body['history'])}")
if "token_usage" in body:
    print(f"  token total: {body['token_usage'].get('total')}")
EOF
}

# Turn 1: establish the context.
python3 -c "import json,sys; json.dump({'body': json.dumps({'question': sys.argv[1]})}, open(sys.argv[2], 'w'))" "$Q1" "$DIR/request1.json"
invoke "$DIR/request1.json" "$DIR/response1.json"
summary "TURN 1" "$DIR/response1.json"

# Turn 2: a follow-up ("their") sent WITH turn 1's history -> expect a flagged query.
python3 -c "
import json, sys
r1 = json.loads(json.load(open(sys.argv[1]))['body'])
json.dump({'body': json.dumps({'question': sys.argv[2], 'history': r1['history']})}, open(sys.argv[3], 'w'))
" "$DIR/response1.json" "$Q2" "$DIR/request2.json"
invoke "$DIR/request2.json" "$DIR/response2.json"
summary "TURN 2 (follow-up)" "$DIR/response2.json"

# Attempt to confirm a DIFFERENT query with turn 2's token -> expect 403.
python3 -c "
import json, sys
r2 = json.loads(json.load(open(sys.argv[1]))['body'])
confirm = dict(r2['confirm']); confirm['sql'] = confirm['sql'].replace(\"'Acme Corp'\", \"'Beta Financial'\")
json.dump({'body': json.dumps({'question': sys.argv[2], 'history': r2['history'], 'confirm': confirm})}, open(sys.argv[3], 'w'))
" "$DIR/response2.json" "$Q2" "$DIR/request_altered.json"
invoke "$DIR/request_altered.json" "$DIR/response_altered.json"
summary "ALTERED CONFIRMATION (Acme Corp -> Beta Financial)" "$DIR/response_altered.json"

# Turn 3: confirm EXACTLY the flagged query, still carrying the conversation.
python3 -c "
import json, sys
r2 = json.loads(json.load(open(sys.argv[1]))['body'])
json.dump({'body': json.dumps({'question': sys.argv[2], 'history': r2['history'], 'confirm': r2['confirm']})}, open(sys.argv[3], 'w'))
" "$DIR/response2.json" "$Q2" "$DIR/request3.json"
invoke "$DIR/request3.json" "$DIR/response3.json"
summary "TURN 3 (exact confirmation)" "$DIR/response3.json"

# Did turn 3 run exactly the SQL that turn 2 flagged?
python3 -c "
import json, sys
s2 = json.loads(json.load(open(sys.argv[1]))['body'])['sql']
s3 = json.loads(json.load(open(sys.argv[2]))['body'])['sql']
print('\nConfirmed query identical to flagged query:', s2 == s3)
" "$DIR/response2.json" "$DIR/response3.json"