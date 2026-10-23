import json

import pytest

from agentstudio.engine.runtime import (
    ExpressionError,
    assistant_message,
    build_messages,
    build_scope,
    http_request_spec,
    http_result,
    json_schema,
    knowledge_context,
    parse_json_output,
    parse_tool_arguments,
    response_format,
    tool_definition,
    tool_message,
    transform,
    validate_inputs,
)

FIELDS = [
    {
        "name": "category",
        "type": "string",
        "enum": ["billing", "technical"],
        "description": "Topic.",
    },
    {"name": "amount", "type": "number"},
    {
        "name": "lines",
        "type": "array",
        "items": "object",
        "fields": [{"name": "sku", "type": "string"}, {"name": "qty", "type": "integer"}],
    },
]


def test_transform_applies_jmespath() -> None:
    data = {"invoices": [{"id": 1, "total": 50}, {"id": 2, "total": 900}]}
    assert transform(data, "invoices[?total > `100`].id") == [2]
    assert transform(json.dumps(data), "length(invoices)") == 2
    assert transform(data, "") == data
    with pytest.raises(ExpressionError, match="JMESPath"):
        transform(data, "invoices[?")


def test_inputs_are_validated_coerced_and_defaulted() -> None:
    fields = [
        {"name": "subject", "type": "string"},
        {"name": "seats", "type": "integer"},
        {"name": "urgent", "type": "boolean", "required": False},
        {"name": "region", "type": "string", "default": "EU"},
    ]
    result = validate_inputs({"subject": "Hi", "seats": "12", "extra": 1}, fields)
    assert result == {"subject": "Hi", "seats": 12, "urgent": None, "region": "EU", "extra": 1}
    with pytest.raises(ExpressionError) as error:
        validate_inputs({"seats": "twelve"}, fields)
    assert "'subject' is required" in str(error.value)
    assert "'seats' must be an integer" in str(error.value)


def test_messages_carry_the_json_contract() -> None:
    messages = build_messages(
        "You triage tickets.", "Ticket: refund", output_mode="json", json_fields=FIELDS
    )
    assert messages[0]["role"] == "system"
    assert "category (string): one of billing, technical. Topic." in messages[0]["content"]
    assert "  - sku (string)" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "Ticket: refund"}
    assert build_messages("", "hello") == [{"role": "user", "content": "hello"}]


def test_response_format_and_schema() -> None:
    assert response_format("text") is None
    assert response_format("json") == {"type": "json_object"}
    schema = json_schema(FIELDS)
    assert schema["required"] == ["category", "amount", "lines"]
    assert schema["properties"]["category"]["enum"] == ["billing", "technical", None]
    assert schema["properties"]["lines"]["items"]["properties"]["qty"] == {
        "type": ["integer", "null"]
    }
    assert response_format("json", FIELDS)["json_schema"]["schema"] == schema  # type: ignore[index]


def test_json_output_is_parsed_and_coerced() -> None:
    text = (
        'Sure!\n```json\n{"category": "billing", "amount": "1,200.50", '
        '"lines": [{"sku": "A", "qty": "2"}]}\n```'
    )
    assert parse_json_output(text, FIELDS) == {
        "category": "billing",
        "amount": 1200.5,
        "lines": [{"sku": "A", "qty": 2}],
    }
    assert parse_json_output('{"free": true}') == {"free": True}
    for bad in ("no json at all", "{broken", "[1, 2]"):
        with pytest.raises(ExpressionError):
            parse_json_output(bad)


def test_tool_definitions_and_messages() -> None:
    http = tool_definition(
        "http",
        {
            "tool_description": "Look up a company.",
            "parameters": [{"name": "domain", "type": "string", "description": "Domain."}],
        },
        "lookup_company",
    )
    assert http["function"]["name"] == "lookup_company"
    assert http["function"]["parameters"]["required"] == ["domain"]
    calc = tool_definition("calculator", {}, "calc")
    assert list(calc["function"]["parameters"]["properties"]) == ["expression"]
    call = {"id": "call_1", "name": "calc", "arguments": '{"expression": "1+1"}'}
    assert assistant_message(None, [call])["tool_calls"][0]["function"]["name"] == "calc"
    assert tool_message("call_1", {"result": 2}) == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"result": 2}',
    }
    assert parse_tool_arguments('{"a": 1}') == {"a": 1}
    with pytest.raises(ExpressionError):
        parse_tool_arguments("[1]")


def test_http_spec_and_result() -> None:
    scope = build_scope({"domain": "globex.example"}, {}, secrets={"TOKEN": "abc"})
    spec = http_request_spec(
        {
            "method": "POST",
            "url": "https://api.example.com/companies/{{inputs.domain}}",
            "headers": [{"key": "Authorization", "value": "Bearer {{secrets.TOKEN}}"}],
            "query": [{"key": "fields", "value": "name,size"}],
            "body_mode": "json",
            "body": '{"domain": "{{inputs.domain}}"}',
        },
        scope,
    )
    assert spec["url"] == "https://api.example.com/companies/globex.example"
    assert spec["headers"] == {"Authorization": "Bearer abc"}
    assert spec["params"] == {"fields": "name,size"}
    assert spec["json"] == {"domain": "globex.example"}
    assert http_result(200, '{"ok": 1}', "application/json; charset=utf-8", "json") == {
        "status": 200,
        "ok": True,
        "json": {"ok": 1},
        "content_type": "application/json",
    }
    assert http_result(500, "oops", "text/plain", "json")["text"] == "oops"


def test_knowledge_context_numbers_sources() -> None:
    context = knowledge_context(
        [
            {"title": "Refund policy", "heading": "Timelines", "text": "Refunds take 5 days."},
            {"title": "FAQ", "text": "Contact support."},
        ]
    )
    assert (
        context
        == "[1] Refund policy > Timelines\nRefunds take 5 days.\n\n[2] FAQ\nContact support."
    )
