"""Fit + timing scoring. Rules only: Claude receives the result and cannot change it.

Fit = 50 x segment win rate / overall win rate, capped at 100.
Small segments are pulled towards the average. Companies under 250 staff are halved.
No history starts at 50. Timing = strongest signal x how recent it is.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CUT_OFF = 50
SMOOTHING_DEALS = 20  # how strongly a small segment is pulled towards the average
SIGNAL_POINTS = {
    "asked_to_talk": 90, "referral": 80, "event": 60,      # inbound
    "ai_rollout": 70, "skills_hiring": 60, "funding": 40,  # outbound
}


def _history() -> dict:
    return json.loads((ROOT / "data" / "segment_history.json").read_text())


def _day(value: str) -> date:
    return date.fromisoformat(value[:10])


def recency_multiplier(days_old: int) -> float:
    if days_old <= 30:
        return 1.0
    return 0.5 if days_old <= 90 else 0.0


def timing_score(case: dict) -> int:
    scoring = case.get("scoring") or {}
    received = _day(case["signal"]["received_at"])
    values = [SIGNAL_POINTS[s["type"]] * recency_multiplier((received - _day(s["date"])).days)
              for s in scoring.get("signals", [])]
    score = round(max(values, default=0))
    return min(score, 20) if scoring.get("recently_disqualified") else score


def fit_score(case: dict, employees: int | None, conflict: bool) -> int | None:
    """None means key company data is missing or conflicting, so fit cannot be scored."""
    scoring = case.get("scoring") or {}
    company = (case.get("lead") or {}).get("company")
    if conflict or not company or not scoring.get("industry"):
        return None
    history = _history()
    overall = history["overall_win_rate"]
    segment = history["segments"].get(f"{scoring.get('region')}|{scoring['industry']}")
    if segment and scoring.get("use_segment_history", True):
        pulled = (segment["wins"] + SMOOTHING_DEALS * overall) / (segment["deals"] + SMOOTHING_DEALS)
        score = 50 * pulled / overall
    else:
        score = 50.0
    if employees is not None and employees < 250:
        score /= 2
    return min(round(score), 100)


def priority(fit: int | None, timing: int) -> str:
    if fit is None:
        return "Unscored"
    if timing >= CUT_OFF:
        return "P1" if fit >= CUT_OFF else "P2"
    return "P3" if fit >= CUT_OFF else "P4"


def overall_score(fit: int | None, timing: int) -> float | None:
    if fit is None:
        return None
    value = (fit + timing) / 2
    return int(value) if value.is_integer() else value


def score_case(case: dict, employees: int | None, conflict: bool) -> dict:
    fit = fit_score(case, employees, conflict)
    timing = timing_score(case)
    return {"fit_score": fit, "timing_score": timing, "priority": priority(fit, timing),
            "score": overall_score(fit, timing)}
