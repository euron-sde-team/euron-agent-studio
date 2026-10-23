import math

import pytest

from agentstudio.engine.runtime import ExpressionError, calculate


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("10 / 4", 2.5),
        ("10 // 4", 2),
        ("10 % 4", 2),
        ("2 ** 10", 1024),
        ("-3 + +5", 2),
        ("round(1234.5678, 2)", 1234.57),
        ("min(3, 1, 2) + max(4, 9)", 10),
        ("abs(-12.5)", 12.5),
        ("sqrt(16)", 4.0),
        ("floor(2.7) + ceil(2.1)", 5),
        ("1250.00 * 0.2", 250.0),
        ("2 * pi", 2 * math.pi),
    ],
)
def test_arithmetic(expression: str, expected: float) -> None:
    assert calculate(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("", "empty"),
        ("1 / 0", "Division by zero"),
        ("__import__('os')", "Unknown function"),
        ("open('x')", "Unknown function"),
        ("x + 1", "Unknown name"),
        ("(1).real", "Only arithmetic"),
        ("[1, 2]", "Only arithmetic"),
        ("1,250 * 2", "Only arithmetic"),
        ("'a' * 3", "Only numbers"),
        ("True + 1", "Only numbers"),
        ("9 ** 999", "too large"),
        ("10 ** 99 * 10 ** 99", "out of range"),
        ("1 +", "Not a valid calculation"),
        ("round(1, ndigits=2)", "Unknown function"),
        ("sqrt(-1)", "Invalid arguments"),
        ("1" * 600, "500 characters"),
    ],
)
def test_anything_but_arithmetic_is_refused(expression: str, message: str) -> None:
    with pytest.raises(ExpressionError, match=message):
        calculate(expression)
