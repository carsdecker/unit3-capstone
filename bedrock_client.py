"""
bedrock_client.py -- shared helper for calling Claude via Bedrock.
(Course file from Deployment Patterns on AWS, plus per-call tokenomics logging.)

Calls Claude through Amazon Bedrock using your AWS credentials -- no API key.
The inference-profile ARN below is the path to Claude Sonnet 4.6 in this account.

Tokenomics (brief Step 6): EVERY Claude call in the system goes through this file,
so logging here means no call can escape the log. Each call is labelled with the
component that made it and logged with its input/output tokens and USD cost.
"""
import boto3
import json
from datetime import datetime, timezone

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

# Claude Sonnet 4.6, Amazon Bedrock on-demand, US East (aws.amazon.com/bedrock/pricing,
# checked 2026-10-16): $3.00 per 1M input tokens, $15.00 per 1M output tokens.
# The page lists no separate price for the us. cross-region profile we call; assumed equal.
PRICE_PER_1M_INPUT = 3.00
PRICE_PER_1M_OUTPUT = 15.00

# /tmp is the only writable folder on Lambda; it also works locally.
CALL_LOG_PATH = "/tmp/claude_calls.jsonl"


def get_model_id() -> str:
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    return f"arn:aws:bedrock:us-east-1:{account_id}:inference-profile/us.anthropic.claude-sonnet-4-6"


def call_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000 * PRICE_PER_1M_INPUT
            + output_tokens / 1_000_000 * PRICE_PER_1M_OUTPUT)


def log_call(component: str, input_tokens: int, output_tokens: int) -> float:
    cost = call_cost(input_tokens, output_tokens)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
    }
    # print() lands in CloudWatch on Lambda; the file keeps a local history.
    print(f"[CLAUDE CALL] {component:<18} in={input_tokens:>5} out={output_tokens:>4} cost=${cost:.6f}")
    with open(CALL_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return cost


def invoke_claude(prompt: str, max_tokens: int = 500, component: str = "unlabelled") -> dict:
    """
    Sends a single-turn prompt to Claude via Bedrock and returns the response
    text alongside token usage and cost. `component` labels the call in the log.
    """
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }
    response = bedrock.invoke_model(modelId=get_model_id(), body=json.dumps(body))
    result = json.loads(response["body"].read())
    input_tokens = result["usage"]["input_tokens"]
    output_tokens = result["usage"]["output_tokens"]
    cost = log_call(component, input_tokens, output_tokens)
    return {
        "text": result["content"][0]["text"],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
    }


def invoke_claude_raw(body: dict, component: str = "unlabelled") -> dict:
    """
    Lower-level helper for calls that need the full Messages API shape --
    system prompts, tool definitions, multi-turn conversations.
    Returns the parsed response as a plain dict. Logged like invoke_claude.
    """
    body = {**body}
    body.setdefault("anthropic_version", "bedrock-2023-05-31")
    response = bedrock.invoke_model(modelId=get_model_id(), body=json.dumps(body))
    result = json.loads(response["body"].read())
    log_call(component, result["usage"]["input_tokens"], result["usage"]["output_tokens"])
    return result