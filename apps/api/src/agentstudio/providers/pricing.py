"""What a model call costs.

Prices are US dollars per million tokens, input and output. The defaults are the public
list prices of common hosted models when this release was cut; contracts and prices change,
so `MODEL_PRICES` (a JSON object) overrides or extends them. Local models (Ollama) cost
nothing; the offline provider uses a configurable simulated price so cost tracking can be
seen working, and every such cost is flagged as simulated.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal

DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o4-mini": (1.10, 4.40),
    "o3": (2.00, 8.00),
}
_MICRO = Decimal("0.000001")


def parse_prices(raw: str) -> dict[str, tuple[float, float]]:
    """`{"model": [input, output]}` from the MODEL_PRICES setting; invalid entries are refused."""
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("MODEL_PRICES must be a JSON object")
    prices: dict[str, tuple[float, float]] = {}
    for model, pair in data.items():
        if not (isinstance(pair, list | tuple) and len(pair) == 2):
            raise ValueError(f"MODEL_PRICES[{model!r}] must be [input, output]")
        prices[str(model)] = (float(pair[0]), float(pair[1]))
    return prices


def cost(prompt_tokens: int, completion_tokens: int, price: tuple[float, float]) -> Decimal:
    total = (
        Decimal(prompt_tokens) * Decimal(str(price[0]))
        + Decimal(completion_tokens) * Decimal(str(price[1]))
    ) / Decimal(1_000_000)
    return total.quantize(_MICRO, rounding=ROUND_HALF_UP)
