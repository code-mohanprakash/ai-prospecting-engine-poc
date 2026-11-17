"""Step 2 (AI): Claude writes the research brief from the evidence pack, as validated JSON."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

MODEL = "claude-opus-5-5"
# Claude API list prices for this model, USD per million tokens (input, output).
PRICE_PER_MTOK = (4.00, 20.00)
PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"

Action = Literal["book_meeting", "nurture", "human_review", "disqualify", "route_to_owner"]


class Claim(BaseModel):
    text: str
    evidence_ids: list[str] = Field(description="IDs like E3 that support this claim")


class Contact(BaseModel):
    name: str
    title: str
    why: str
    evidence_ids: list[str]


class Brief(BaseModel):
    summary: str = Field(description="Two sentences: who they are and what they want")
    why_now: list[Claim]
    who_to_contact: list[Contact]
    product_angle: Literal["apprenticeships", "mastry", "both", "unclear"]
    angle_reason: Claim
    recommended_action: Action
    action_reason: str
    missing_or_conflicting: list[str]
    suggested_opener: str
    confidence: Literal["high", "medium", "low"]


def load_prompt(version: str = "v2") -> str:
    return (PROMPT_DIR / f"brief_{version}.md").read_text()


def write_brief(client: anthropic.Anthropic, evidence: list[dict], decisions: dict,
                prompt_version: str = "v2") -> dict:
    """One Claude call. Returns the brief plus run metadata (latency, tokens, cost, errors)."""
    user = (
        "EVIDENCE:\n" + json.dumps(evidence, ensure_ascii=False, indent=1)
        + "\n\nSYSTEM DECISIONS (fixed, do not change):\n" + json.dumps(decisions, ensure_ascii=False, indent=1)
    )
    started = time.time()
    meta = {"model": MODEL, "prompt_version": prompt_version}
    try:
        resp = client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=load_prompt(prompt_version),
            messages=[{"role": "user", "content": user}],
            output_format=Brief,
            output_config={"effort": "medium"},
            # If a safety classifier declines, the API retries on a fallback model in the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError as e:
        return {**meta, "brief": None, "error": f"rate_limited: {e.message}", "latency_s": round(time.time() - started, 1)}
    except anthropic.APIStatusError as e:
        return {**meta, "brief": None, "error": f"api_error {e.status_code}: {e.message}", "latency_s": round(time.time() - started, 1)}
    except anthropic.APIConnectionError:
        return {**meta, "brief": None, "error": "network_error", "latency_s": round(time.time() - started, 1)}

    latency = time.time() - started
    usage = resp.usage
    cost = usage.input_tokens / 1e6 * PRICE_PER_MTOK[0] + usage.output_tokens / 1e6 * PRICE_PER_MTOK[1]
    meta.update({
        "served_by": resp.model,
        "latency_s": round(latency, 1),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": round(cost, 4),
        "request_id": resp._request_id,
    })
    if resp.stop_reason == "refusal":
        return {**meta, "brief": None, "error": "refusal"}
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        return {**meta, "brief": None, "error": f"no_valid_output (stop_reason={resp.stop_reason})"}
    return {**meta, "brief": resp.parsed_output.model_dump(), "error": None}
