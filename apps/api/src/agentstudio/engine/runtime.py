"""The flow runtime library: what each node computes from its inputs.

Templates, conditions, the calculator, JSON transforms, input validation, prompt assembly,
JSON output parsing, tool definitions and result shapes all live here, and nowhere else.
The engine imports this module, and the Python exporter embeds this file verbatim into every
exported script. That is what makes an exported script behave exactly like the engine, so
this module must stay self-contained: the standard library, jmespath, and re2 when it is
installed (the server always has it; an exported script falls back to `re`).
"""

from __future__ import annotations

import ast
import contextlib
import json
import math
import operator
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import jmespath
from jmespath.exceptions import JMESPathError

try:  # Linear-time regular expressions: user patterns cannot stall the worker.
    import re2 as _user_regex
except ImportError:  # pragma: no cover - exported scripts on machines without re2
    _user_regex = re


class ExpressionError(ValueError):
    """A template, condition, calculation or transform that cannot be evaluated."""


# --------------------------------------------------------------------------------------
# Values and paths
# --------------------------------------------------------------------------------------

_TEMPLATE = re.compile(r"\{\{(.*?)\}\}", re.S)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INDEX = re.compile(r"\[\s*(-?\d+)\s*\]")


def to_text(value: Any) -> str:
    """How a value appears inside rendered text: JSON for structures, plain otherwise."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    if isinstance(value, int | float):
        return repr(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def parse_path(path: str) -> list[str | int]:
    """`classify.json.items[0].name` becomes ["classify", "json", "items", 0, "name"]."""
    text = path.strip()
    parts: list[str | int] = []
    position = 0
    expect_name = True
    while position < len(text):
        if expect_name:
            match = _IDENT.match(text, position)
            if not match:
                raise ExpressionError(f"Invalid reference: {path!r}")
            parts.append(match.group(0))
            position = match.end()
            expect_name = False
            continue
        if text[position] == ".":
            position += 1
            expect_name = True
            continue
        match = _INDEX.match(text, position)
        if not match:
            raise ExpressionError(f"Invalid reference: {path!r}")
        parts.append(int(match.group(1)))
        position = match.end()
    if not parts or expect_name:
        raise ExpressionError(f"Invalid reference: {path!r}")
    return parts


def resolve(scope: Mapping[str, Any], parts: Sequence[str | int]) -> Any:
    """Walk a parsed path through dicts and lists; anything missing resolves to None."""
    current: Any = scope
    for part in parts:
        if isinstance(part, int):
            if isinstance(current, list | tuple) and -len(current) <= part < len(current):
                current = current[part]
            else:
                return None
        elif isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, list | tuple) and part == "length":
            current = len(current)
        else:
            return None
        if current is None:
            return None
    return current


# --------------------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------------------


def _split_top_level(text: str, separator: str) -> list[str]:
    """Split on `separator` outside quotes and parentheses."""
    pieces: list[str] = []
    depth = 0
    quote = ""
    start = 0
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == separator and depth == 0:
            pieces.append(text[start:index])
            start = index + 1
    pieces.append(text[start:])
    return pieces


def _literal(text: str) -> Any:
    """A filter argument: JSON (so "\\n" is a newline in double quotes), or raw in single quotes."""
    token = text.strip()
    if len(token) >= 2 and token[0] == token[-1] == "'":
        return token[1:-1]
    try:
        return json.loads(token)
    except ValueError as exc:
        raise ExpressionError(f"Invalid filter argument: {text!r}") from exc


def _filter_join(value: Any, separator: Any = ", ") -> Any:
    if isinstance(value, list | tuple):
        return str(separator).join(to_text(item) for item in value)
    return value


def _filter_default(value: Any, fallback: Any = "") -> Any:
    return fallback if value is None or value in ("", [], {}) else value


def _filter_round(value: Any, digits: Any = 0) -> Any:
    number = as_number(value)
    if number is None:
        return value
    return round(number, int(digits))


FILTERS: dict[str, Callable[..., Any]] = {
    "json": lambda value: json.dumps(value, ensure_ascii=False, default=str),
    "upper": lambda value: to_text(value).upper(),
    "lower": lambda value: to_text(value).lower(),
    "trim": lambda value: to_text(value).strip(),
    "length": lambda value: len(value) if isinstance(value, str | list | tuple | dict) else 0,
    "first": lambda value: value[0] if isinstance(value, list | tuple) and value else None,
    "last": lambda value: value[-1] if isinstance(value, list | tuple) and value else None,
    "join": _filter_join,
    "default": _filter_default,
    "round": _filter_round,
}


def parse_expression(expression: str) -> tuple[list[str | int], list[tuple[str, list[Any]]]]:
    """A template expression: a path followed by `| filter` or `| filter(arg, ...)` parts."""
    pieces = _split_top_level(expression, "|")
    path = parse_path(pieces[0])
    filters: list[tuple[str, list[Any]]] = []
    for raw in pieces[1:]:
        piece = raw.strip()
        name, _, rest = piece.partition("(")
        name = name.strip()
        if name not in FILTERS:
            raise ExpressionError(f"Unknown filter: {name!r}")
        args: list[Any] = []
        if rest:
            if not rest.rstrip().endswith(")"):
                raise ExpressionError(f"Unclosed filter arguments: {piece!r}")
            inner = rest.rstrip()[:-1]
            args = [_literal(arg) for arg in _split_top_level(inner, ",") if arg.strip()]
        filters.append((name, args))
    return path, filters


def evaluate(expression: str, scope: Mapping[str, Any]) -> Any:
    path, filters = parse_expression(expression)
    value = resolve(scope, path)
    for name, args in filters:
        value = FILTERS[name](value, *args)
    return value


def render(template: str, scope: Mapping[str, Any]) -> str:
    """Render a template to text. Unresolved references render as empty text."""
    if "{{" not in template:
        return template
    return _TEMPLATE.sub(lambda match: to_text(evaluate(match.group(1), scope)), template)


def render_value(template: str, scope: Mapping[str, Any]) -> Any:
    """Like `render`, but a template that is exactly one `{{ ... }}` keeps the value's type."""
    stripped = template.strip()
    match = _TEMPLATE.fullmatch(stripped)
    if match and "{{" not in match.group(1):
        return evaluate(match.group(1), scope)
    return render(template, scope)


def template_paths(template: str) -> list[list[str | int]]:
    """Every reference path in a template (used by validation and by secret masking)."""
    paths: list[list[str | int]] = []
    for match in _TEMPLATE.finditer(template):
        path, _ = parse_expression(match.group(1))
        paths.append(path)
    return paths


def build_scope(
    inputs: Mapping[str, Any],
    outputs: Mapping[str, Any],
    *,
    loops: Sequence[tuple[str, Any, int]] = (),
    args: Mapping[str, Any] | None = None,
    secrets: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The names a template can see: inputs, upstream outputs, loop items, tool arguments."""
    scope: dict[str, Any] = dict(outputs)
    scope["inputs"] = dict(inputs)
    scope["secrets"] = dict(secrets or {})
    for loop_id, item, index in loops:
        scope[loop_id] = {"item": item, "index": index}
    if loops:
        scope["item"] = loops[-1][1]
        scope["index"] = loops[-1][2]
    if args is not None:
        scope["args"] = dict(args)
    return scope


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------


def _coerce(name: str, kind: str, value: Any) -> Any:
    if kind == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, int | float) and not isinstance(value, bool):
            return to_text(value)
    elif kind in ("number", "integer"):
        number = as_number(value)
        if number is not None:
            if kind == "integer":
                if float(number).is_integer():
                    return int(number)
            else:
                return number
    elif kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false", "yes", "no"):
            return value.strip().lower() in ("true", "yes")
    elif kind == "object":
        if isinstance(value, dict):
            return value
    elif kind == "array":
        if isinstance(value, list):
            return value
    raise ExpressionError(f"Input {name!r} must be {'an' if kind[0] in 'aio' else 'a'} {kind}.")


def validate_inputs(
    inputs: Mapping[str, Any], fields: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Check run inputs against the Start node's fields, coerce simple types, apply defaults."""
    result: dict[str, Any] = {}
    problems: list[str] = []
    for field in fields:
        name = field["name"]
        kind = field.get("type", "string")
        value = inputs.get(name)
        if value is None or value == "":
            if field.get("default") is not None:
                result[name] = field["default"]
            elif field.get("required", True):
                problems.append(f"Input {name!r} is required.")
            else:
                result[name] = None
            continue
        try:
            result[name] = _coerce(name, kind, value)
        except ExpressionError as exc:
            problems.append(str(exc))
    for name, value in inputs.items():
        if name not in result and not any(field["name"] == name for field in fields):
            result[name] = value
    if problems:
        raise ExpressionError(" ".join(problems))
    return result


# --------------------------------------------------------------------------------------
# Conditions
# --------------------------------------------------------------------------------------


def as_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        for symbol in ("$", "\N{EURO SIGN}", "\N{POUND SIGN}", "\N{INDIAN RUPEE SIGN}", "%"):
            cleaned = cleaned.replace(symbol, "")
        try:
            number = float(cleaned)
        except ValueError:
            return None
        return int(number) if number.is_integer() and "." not in cleaned else number
    return None


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list | tuple | dict):
        return not value
    return False


def _norm(value: Any) -> str:
    return to_text(value).strip().lower()


def _compare(left: Any, right: Any, op: Callable[[float, float], bool]) -> bool:
    a, b = as_number(left), as_number(right)
    if a is None or b is None:
        return False
    return op(a, b)


def _equals(left: Any, right: Any) -> bool:
    a, b = as_number(left), as_number(right)
    if a is not None and b is not None:
        return a == b
    return _norm(left) == _norm(right)


def _contains(left: Any, right: Any) -> bool:
    if isinstance(left, list | tuple):
        return any(_norm(item) == _norm(right) for item in left)
    return _norm(right) in _norm(left)


def _in_list(left: Any, right: Any) -> bool:
    options = right if isinstance(right, list) else to_text(right).split(",")
    return _norm(left) in {_norm(option) for option in options}


def _matches(left: Any, right: Any) -> bool:
    pattern = to_text(right)
    if len(pattern) > 500:
        raise ExpressionError("Regular expressions are limited to 500 characters.")
    try:
        return _user_regex.search(pattern, to_text(left)[:100_000]) is not None
    except Exception as exc:
        raise ExpressionError(f"Invalid regular expression: {pattern!r}") from exc


OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "equals": _equals,
    "not_equals": lambda left, right: not _equals(left, right),
    "contains": _contains,
    "not_contains": lambda left, right: not _contains(left, right),
    "starts_with": lambda left, right: _norm(left).startswith(_norm(right)),
    "ends_with": lambda left, right: _norm(left).endswith(_norm(right)),
    "greater_than": lambda left, right: _compare(left, right, operator.gt),
    "greater_or_equal": lambda left, right: _compare(left, right, operator.ge),
    "less_than": lambda left, right: _compare(left, right, operator.lt),
    "less_or_equal": lambda left, right: _compare(left, right, operator.le),
    "is_empty": lambda left, _right: _is_empty(left),
    "is_not_empty": lambda left, _right: not _is_empty(left),
    "in_list": _in_list,
    "matches": _matches,
}
UNARY_OPERATORS = frozenset({"is_empty", "is_not_empty"})


def evaluate_rule(rule: Mapping[str, Any], scope: Mapping[str, Any]) -> bool:
    name = rule.get("operator", "equals")
    if name not in OPERATORS:
        raise ExpressionError(f"Unknown operator: {name!r}")
    left = render_value(rule.get("left", ""), scope)
    right = render_value(rule.get("right", ""), scope) if name not in UNARY_OPERATORS else None
    return OPERATORS[name](left, right)


def choose_route(routes: Sequence[Mapping[str, Any]], scope: Mapping[str, Any]) -> str:
    """The id of the first route whose rules match, or "else"."""
    for route in routes:
        rules = route.get("rules") or []
        if not rules:
            continue
        results = (evaluate_rule(rule, scope) for rule in rules)
        matched = any(results) if route.get("match", "all") == "any" else all(results)
        if matched:
            return str(route["id"])
    return "else"


def route_handle(route_id: str) -> str:
    return "else" if route_id == "else" else f"route_{route_id}"


# --------------------------------------------------------------------------------------
# Calculator
# --------------------------------------------------------------------------------------

_BINARY: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "round": round,
    "min": min,
    "max": max,
    "abs": abs,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}
_MAX_MAGNITUDE = 1e100


def _calc(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _calc(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise ExpressionError("Only numbers are allowed in calculations.")
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ExpressionError(f"Unknown name in calculation: {node.id!r}")
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_calc(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _calc(node.left), _calc(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
            raise ExpressionError("That power is too large to calculate.")
        try:
            value = _BINARY[type(node.op)](left, right)
        except ZeroDivisionError as exc:
            raise ExpressionError("Division by zero.") from exc
        if isinstance(value, complex) or abs(value) > _MAX_MAGNITUDE:
            raise ExpressionError("The result is out of range.")
        return value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _FUNCTIONS.get(node.func.id)
        if function is None or node.keywords:
            raise ExpressionError(f"Unknown function in calculation: {node.func.id!r}")
        try:
            return function(*[_calc(arg) for arg in node.args])
        except (TypeError, ValueError) as exc:
            raise ExpressionError(f"Invalid arguments to {node.func.id}().") from exc
    raise ExpressionError("Only arithmetic is allowed in calculations.")


def calculate(expression: str) -> int | float:
    """Evaluate arithmetic: numbers, + - * / // % **, parentheses and a few functions."""
    text = expression.strip()
    if not text:
        raise ExpressionError("The calculation is empty.")
    if len(text) > 500:
        raise ExpressionError("Calculations are limited to 500 characters.")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"Not a valid calculation: {expression!r}") from exc
    value = _calc(tree)
    if not isinstance(value, int | float) or (isinstance(value, float) and math.isnan(value)):
        raise ExpressionError("The result is not a number.")
    return value


# --------------------------------------------------------------------------------------
# JSON transforms
# --------------------------------------------------------------------------------------


def transform(data: Any, expression: str) -> Any:
    """Apply a JMESPath expression (https://jmespath.org) to data."""
    if not expression.strip():
        return data
    if isinstance(data, str):
        with contextlib.suppress(ValueError):
            data = json.loads(data)
    try:
        return jmespath.search(expression, data)
    except JMESPathError as exc:
        raise ExpressionError(f"Invalid JMESPath expression: {exc}") from exc


# --------------------------------------------------------------------------------------
# Model prompts and structured output
# --------------------------------------------------------------------------------------

_JSON_TYPES = {
    "string": "string",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}


def _field_schema(field: Mapping[str, Any]) -> dict[str, Any]:
    kind = _JSON_TYPES.get(field.get("type", "string"), "string")
    schema: dict[str, Any] = {"type": [kind, "null"]}
    if field.get("description"):
        schema["description"] = field["description"]
    if field.get("enum") and kind == "string":
        schema["enum"] = [*field["enum"], None]
    nested = field.get("fields") or []
    if kind == "object" and nested:
        schema.update(_object_schema(nested))
        schema["type"] = ["object", "null"]
    if kind == "array":
        item_kind = field.get("items", "string")
        if item_kind == "object" and nested:
            schema["items"] = _object_schema(nested)
        else:
            schema["items"] = {"type": _JSON_TYPES.get(item_kind, "string")}
    return schema


def _object_schema(fields: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {field["name"]: _field_schema(field) for field in fields},
        "required": [field["name"] for field in fields],
        "additionalProperties": False,
    }


def json_schema(fields: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The JSON schema a model is asked to follow in JSON output mode."""
    return _object_schema(fields)


def _describe_field(field: Mapping[str, Any], indent: str = "- ") -> list[str]:
    kind = field.get("type", "string")
    if kind == "array":
        kind = f"array of {field.get('items', 'string')}"
    line = f"{indent}{field['name']} ({kind})"
    if field.get("enum"):
        line += ": one of " + ", ".join(str(value) for value in field["enum"])
    if field.get("description"):
        line += f". {field['description']}"
    lines = [line]
    for nested in field.get("fields") or []:
        lines.extend(_describe_field(nested, "  " + indent))
    return lines


def build_messages(
    system: str,
    prompt: str,
    *,
    output_mode: str = "text",
    json_fields: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """The chat messages for a Prompt node or an Agent's task, after rendering."""
    instructions = system.strip()
    if output_mode == "json":
        described = [line for field in json_fields for line in _describe_field(field)]
        rule = "Respond with a single JSON object and nothing else."
        if described:
            rule += " Use exactly these fields:\n" + "\n".join(described)
        instructions = f"{instructions}\n\n{rule}".strip()
    messages: list[dict[str, Any]] = []
    if instructions:
        messages.append({"role": "system", "content": instructions})
    messages.append({"role": "user", "content": prompt})
    return messages


def response_format(
    output_mode: str, json_fields: Sequence[Mapping[str, Any]] = ()
) -> dict[str, Any] | None:
    """The OpenAI-style `response_format` for a node, or None for free text."""
    if output_mode != "json":
        return None
    if not json_fields:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": "output", "schema": json_schema(json_fields), "strict": False},
    }


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def _coerce_field(value: Any, field: Mapping[str, Any]) -> Any:
    kind = field.get("type", "string")
    if value is None:
        return None
    if kind in ("number", "integer"):
        number = as_number(value)
        if number is None:
            return None
        return int(number) if kind == "integer" and float(number).is_integer() else number
    if kind == "boolean" and isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    if kind == "object" and isinstance(value, dict) and field.get("fields"):
        return {f["name"]: _coerce_field(value.get(f["name"]), f) for f in field["fields"]}
    if kind == "array" and isinstance(value, list) and field.get("fields"):
        return [
            {f["name"]: _coerce_field(item.get(f["name"]), f) for f in field["fields"]}
            if isinstance(item, dict)
            else item
            for item in value
        ]
    return value


def parse_json_output(text: str, json_fields: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Read a model's JSON answer, tolerating code fences and surrounding prose."""
    candidate = _FENCE.sub("", text.strip())
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end < start:
        raise ExpressionError("The model did not return a JSON object.")
    try:
        data = json.loads(candidate[start : end + 1])
    except ValueError as exc:
        raise ExpressionError("The model returned malformed JSON.") from exc
    if not isinstance(data, dict):
        raise ExpressionError("The model did not return a JSON object.")
    if json_fields:
        return {
            field["name"]: _coerce_field(data.get(field["name"]), field) for field in json_fields
        }
    return data


# --------------------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------------------

TOOL_PARAMETERS: dict[str, list[dict[str, Any]]] = {
    "knowledge": [
        {"name": "query", "type": "string", "description": "What to search for.", "required": True}
    ],
    "calculator": [
        {
            "name": "expression",
            "type": "string",
            "description": "An arithmetic expression, for example (1200 * 12) * 0.9.",
            "required": True,
        }
    ],
    "json_transform": [
        {
            "name": "data",
            "type": "object",
            "description": "The JSON data to transform.",
            "required": True,
        }
    ],
}


def tool_parameters(kind: str, config: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(config.get("parameters") or []) if kind == "http" else TOOL_PARAMETERS.get(kind, [])


def tool_definition(kind: str, config: Mapping[str, Any], name: str) -> dict[str, Any]:
    """The OpenAI-style function definition an Agent offers its model for a tool node."""
    parameters = tool_parameters(kind, config)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": config.get("tool_description") or f"The {name} tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    p["name"]: {
                        "type": _JSON_TYPES.get(p.get("type", "string"), "string"),
                        "description": p.get("description", ""),
                    }
                    for p in parameters
                },
                "required": [p["name"] for p in parameters if p.get("required", True)],
            },
        },
    }


def tool_result_content(result: Any) -> str:
    """How a tool's result is handed back to the model."""
    return json.dumps(result, ensure_ascii=False, default=str)


def assistant_message(
    content: str | None, tool_calls: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """The assistant turn that asked for tool calls, as it is sent back to the model."""
    message: dict[str, Any] = {"role": "assistant", "content": content or None}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": call["arguments"]},
            }
            for call in tool_calls
        ]
    return message


def tool_message(call_id: str, result: Any) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": tool_result_content(result)}


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw or "{}")
    except ValueError as exc:
        raise ExpressionError("The model sent tool arguments that are not JSON.") from exc
    if not isinstance(data, dict):
        raise ExpressionError("The model sent tool arguments that are not an object.")
    return data


# --------------------------------------------------------------------------------------
# HTTP requests and knowledge results
# --------------------------------------------------------------------------------------


def http_request_spec(config: Mapping[str, Any], scope: Mapping[str, Any]) -> dict[str, Any]:
    """Render an HTTP node's method, URL, headers, query and body."""
    spec: dict[str, Any] = {
        "method": config.get("method", "GET"),
        "url": render(config.get("url", ""), scope).strip(),
        "headers": {
            pair["key"]: render(pair.get("value", ""), scope)
            for pair in config.get("headers") or []
            if pair.get("key")
        },
        "params": {
            pair["key"]: render(pair.get("value", ""), scope)
            for pair in config.get("query") or []
            if pair.get("key")
        },
    }
    mode = config.get("body_mode", "none")
    if mode == "json":
        body = render_value(config.get("body", ""), scope)
        if isinstance(body, str):
            try:
                body = json.loads(body) if body.strip() else None
            except ValueError as exc:
                raise ExpressionError("The request body is not valid JSON.") from exc
        spec["json"] = body
    elif mode == "text":
        spec["content"] = render(config.get("body", ""), scope)
    return spec


def http_result(status: int, text: str, content_type: str, expect: str) -> dict[str, Any]:
    """An HTTP node's output: status, ok, and the body as JSON or text."""
    result: dict[str, Any] = {"status": status, "ok": 200 <= status < 300}
    if expect == "json":
        try:
            result["json"] = json.loads(text) if text.strip() else None
        except ValueError:
            result["json"] = None
            result["text"] = text
    else:
        result["text"] = text
    result["content_type"] = content_type.split(";")[0].strip()
    return result


def knowledge_context(results: Sequence[Mapping[str, Any]]) -> str:
    """Search results formatted as numbered sources for a prompt."""
    blocks = []
    for number, result in enumerate(results, start=1):
        title = result.get("title", "")
        if result.get("heading"):
            title = f"{title} > {result['heading']}"
        blocks.append(f"[{number}] {title}\n{result.get('text', '')}".strip())
    return "\n\n".join(blocks)
