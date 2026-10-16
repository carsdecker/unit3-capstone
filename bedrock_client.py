"""
bedrock_client.py -- shared helper for calling Claude via Bedrock.
(Course file from Deployment Patterns on AWS, unchanged.)

Calls Claude through Amazon Bedrock using your AWS credentials -- no API key.
The inference-profile ARN below is the path to Claude Sonnet 4.6 in this account.
"""
import boto3
import json

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")


def get_model_id() -> str:
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    return f"arn:aws:bedrock:us-east-1:{account_id}:inference-profile/us.anthropic.claude-sonnet-4-6"


def invoke_claude(prompt: str, max_tokens: int = 500) -> dict:
    """
    Sends a single-turn prompt to Claude via Bedrock and returns the response
    text alongside token usage. Use this for simple prompt-in, text-out calls.
    """
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }
    response = bedrock.invoke_model(modelId=get_model_id(), body=json.dumps(body))
    result = json.loads(response["body"].read())
    return {
        "text": result["content"][0]["text"],
        "input_tokens": result["usage"]["input_tokens"],
        "output_tokens": result["usage"]["output_tokens"]
    }


def invoke_claude_raw(body: dict) -> dict:
    """
    Lower-level helper for calls that need the full Messages API shape --
    system prompts, tool definitions, multi-turn conversations.
    Returns the parsed response as a plain dict.
    """
    body = {**body}
    body.setdefault("anthropic_version", "bedrock-2023-05-31")
    response = bedrock.invoke_model(modelId=get_model_id(), body=json.dumps(body))
    return json.loads(response["body"].read())