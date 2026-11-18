"""The API price list of the token ledger (brain.usage): USD per million tokens by model, the long-prompt and fast
mode prices, one message's cost and its split by token kind, the rates of a token read and written (what
``brain usage --by context`` and ``--by output`` price, brain.spend). Its names are read as ``usage.X`` too.
"""

from __future__ import annotations

# USD per million tokens: input, output, cache read, cache write 5 min, cache write 1 h. The claude-api reference's
# price list (cached 2026-10-06; cache reads as listed, cache writes 1.25x and 2x the input), checked against Claude
# Code's totalCostUSD (cost-state records): Opus 5.5 sessions reproduce it to the cent.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5, 20.0),
    "claude-mythos-5-1": (10.0, 50.0, 0.25, 12.5, 20.0),
    "claude-fable-5": (10.0, 50.0, 1.0, 12.5, 20.0),
    "claude-opus-5-5": (4.0, 20.0, 0.2, 5.0, 8.0),
    "claude-opus-5": (5.0, 25.0, 0.5, 6.25, 10.0),
    "claude-opus-4-8": (5.0, 25.0, 0.5, 6.25, 10.0),
    "claude-opus-4-7": (5.0, 25.0, 0.5, 6.25, 10.0),
    "claude-opus-4-6": (5.0, 25.0, 0.5, 6.25, 10.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.2, 2.5, 4.0),
    "claude-sonnet-5": (2.0, 10.0, 0.2, 2.5, 4.0),
    "claude-sonnet-4-6": (3.0, 15.0, 0.3, 3.75, 6.0),
    "claude-haiku-5-5": (0.1, 0.5, 0.01, 0.125, 0.2),
    "claude-haiku-4-5": (1.0, 5.0, 0.1, 1.25, 2.0),
}
LONG_PROMPT = {"claude-haiku-5-5": (100_000, (0.5, 2.5, 0.05, 0.625, 1.0))}  # above that context, these prices
FAMILIES = ("fable", "mythos", "opus", "sonnet", "haiku")  # an unknown model: its family's latest price
FAST = 2.0  # fast mode (usage.speed "fast"): twice the price


def _price_table(model: str, prices: dict | None = None) -> tuple | None:
    table = {**PRICES, **{k: tuple(v) for k, v in (prices or {}).items()}}
    if model in table:
        return table[model]
    for fam in FAMILIES:
        if fam in (model or ""):
            return next((v for k, v in table.items() if fam in k), None)
    return None


def _table_for(part: dict, model: str, prices: dict | None = None) -> tuple | None:
    """The price list that applies to one message: its model's, the long-prompt prices above their threshold."""
    table = _price_table(model, prices)
    long = LONG_PROMPT.get(model)
    if table and long and part.get("input", 0) + part.get("cache_read", 0) + part.get("cache_write", 0) > long[0]:
        table = long[1]
    return table


def cost_parts(part: dict, model: str, speed: str = "", prices: dict | None = None) -> dict | None:
    """One message's price split into input, output, cache read and cache write (USD), None for an unknown model."""
    table = _table_for(part, model, prices)
    if table is None:
        return None
    p_in, p_out, p_read, p_w5, p_w1 = table
    w1, w5 = part.get("cache_write_1h", 0), part.get("cache_write_5m", 0)
    rest = max(0, part.get("cache_write", 0) - w1 - w5)  # a write with no TTL split: priced at 5 min
    m = (FAST if speed == "fast" else 1.0) / 1e6
    return {"input": part.get("input", 0) * p_in * m, "output": part.get("output", 0) * p_out * m,
            "read": part.get("cache_read", 0) * p_read * m, "write": ((w5 + rest) * p_w5 + w1 * p_w1) * m}


def message_cost(part: dict, model: str, speed: str = "", prices: dict | None = None) -> float | None:
    """The API price of one message's tokens (``transcript._usage_tokens``), None for an unknown model."""
    parts = cost_parts(part, model, speed, prices)
    return None if parts is None else parts["input"] + parts["output"] + parts["read"] + parts["write"]


def token_rates(part: dict, model: str, speed: str = "", prices: dict | None = None) -> tuple[float, float]:
    """(read, write) USD per token for one message: what a token of its context costs it, and what writing a new
    token costs (the TTL it wrote with: 1 h when it wrote any 1 h token, else 5 min); (0, 0) for an unknown model."""
    table = _table_for(part, model, prices)
    if table is None:
        return 0.0, 0.0
    m = (FAST if speed == "fast" else 1.0) / 1e6
    return table[2] * m, (table[4] if part.get("cache_write_1h", 0) else table[3]) * m


def tokens_cost(by_model: dict, prices: dict | None = None) -> float:
    """The price of ``{model: tokens}`` (an SR's tokens_by_model): what the cockpit shows without a scan."""
    return sum(message_cost(t, m, prices=prices) or 0.0 for m, t in (by_model or {}).items())
