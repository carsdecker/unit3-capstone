# tests/test_registry.py — Brief Step 3: registry structure and description rules.
# FREE: no Claude calls (call_tool is only exercised with an unknown name).
from tool_registry import TOOL_REGISTRY, get_all_schemas, call_tool

STANDARD_KEYS = {"success", "answer", "sources", "metadata"}


def test_both_tools_registered():
    assert set(TOOL_REGISTRY) == {"sql_agent", "retrieval_agent"}
    assert [s["name"] for s in get_all_schemas()] == ["sql_agent", "retrieval_agent"]


def test_each_description_says_what_it_is_for_and_not_for():
    # The brief's pass condition: each description names what the tool is for
    # AND what it is not for.
    for schema in get_all_schemas():
        description = schema["description"]
        print(f"\n  {schema['name']}: {description}")
        assert description.startswith("Use for")
        assert "Do NOT use for" in description


def test_unknown_tool_fails_safely_with_standard_shape():
    result = call_tool("nonexistent_tool", "anything")
    assert set(result) == STANDARD_KEYS
    assert result["success"] is False