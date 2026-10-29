"""Optional LLM mode: one Claude API call per decision, with a hard spending cap.

Only used by the `mode=llm` agent team (att/agents/llm_coordinator.py). Nothing in the main results
calls this. The API key comes from the ANTHROPIC_API_KEY environment variable or the gitignored
`.env` file in the repo root -- never from git.

Spend is tracked in results/llm/spend.json from each response's token usage. Before every call we
check that even a worst-case call (full max_tokens of output) can't push the total over the cap;
if it could, we stop with BudgetExceeded instead of calling.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from att import config

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Conservative prices (USD per million tokens) used for the cap: Claude Opus 5.5 is $4 in / $20 out,
# but a refusal fallback may run on a model priced up to $5 / $25, so the cap uses the higher rates.
PRICE_IN, PRICE_OUT, PRICE_CACHE_WRITE, PRICE_CACHE_READ = 5.0, 25.0, 6.25, 0.5
LEDGER = config.ROOT / "results" / "llm" / "spend.json"


class BudgetExceeded(RuntimeError):
    pass


class LLMError(RuntimeError):
    """The call failed or returned something unusable; the caller falls back to rule mode."""


def api_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    env = config.ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def cap_usd() -> float:
    return float(os.environ.get("ATT_LLM_CAP_USD", "25"))


def read_ledger() -> dict[str, Any]:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"model": MODEL, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 0,
            "cache_read_tokens": 0, "usd_upper_bound": 0.0}


def _record(usage: Any) -> dict[str, Any]:
    led = read_ledger()
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    usd = (inp * PRICE_IN + out * PRICE_OUT + cw * PRICE_CACHE_WRITE + cr * PRICE_CACHE_READ) / 1e6
    led["calls"] += 1
    led["input_tokens"] += inp
    led["output_tokens"] += out
    led["cache_write_tokens"] += cw
    led["cache_read_tokens"] += cr
    led["usd_upper_bound"] = round(led["usd_upper_bound"] + usd, 6)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(led, indent=1) + "\n")
    return {"input_tokens": inp, "output_tokens": out, "cache_write_tokens": cw, "cache_read_tokens": cr,
            "usd_upper_bound": round(usd, 6)}


async def ask_json(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    """One Claude call that must answer with JSON matching `schema`.

    Returns {"data": parsed JSON, "usage": ..., "model": served model, "request_id": ..., "raw": text}.
    Raises BudgetExceeded (stop everything) or LLMError (caller falls back to rules).
    """
    import anthropic  # imported here so rule mode never needs the package

    key = api_key()
    if not key:
        raise LLMError("no ANTHROPIC_API_KEY in the environment or .env")
    worst = (len(system) + len(user)) / 3 * PRICE_IN / 1e6 + MAX_TOKENS * PRICE_OUT / 1e6
    spent = read_ledger()["usd_upper_bound"]
    if spent + worst > cap_usd():
        raise BudgetExceeded(f"spent ${spent:.2f} (upper bound); a worst-case call could pass the ${cap_usd():.2f} cap")
    client = anthropic.AsyncAnthropic(api_key=key)
    try:
        resp = await client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            betas=[FALLBACK_BETA],
            fallbacks="default",  # if a safety classifier declines, the API retries on another model
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIStatusError as e:
        raise LLMError(f"API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError(f"connection error: {e}") from e
    finally:
        await client.close()
    usage = _record(resp.usage)
    meta = {"usage": usage, "model": resp.model, "request_id": getattr(resp, "_request_id", None),
            "stop_reason": resp.stop_reason}
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise LLMError(f"stop_reason={resp.stop_reason}")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"invalid JSON: {e}") from e
    return {"data": data, "raw": text, **meta}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]
