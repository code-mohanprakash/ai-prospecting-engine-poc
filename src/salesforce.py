"""Step 4 (code): what gets written to Salesforce, and what happens when a rep edits it.

The engine writes only its own AI_* fields. Reps can edit four of them. If a rep edits one,
a Salesforce Flow adds it to AI_Locked_Fields__c and the engine stops writing it.
The draft opener is not written to Salesforce. It stays in Slack.
"""

from __future__ import annotations

from datetime import datetime, timezone

from checks import HARD, LIVE, SOFT

REP_EDITABLE_FIELDS = ["AI_Why_Now__c", "AI_Brief_Summary__c", "AI_Recommended_Action__c", "AI_Product_Angle__c"]
SYSTEM_FIELDS = ["AI_Fit_Score__c", "AI_Timing_Score__c", "AI_Priority__c", "AI_Route_To__c", "AI_Evidence__c",
                 "AI_Flags__c", "AI_Confidence__c", "AI_Run_Id__c", "AI_Generated_At__c"]
AI_FIELDS = REP_EDITABLE_FIELDS + SYSTEM_FIELDS


def to_payload(decisions: dict, brief: dict, evidence: list[dict], run: dict) -> dict:
    """Map one brief to Lead or Account fields."""
    used = sorted({i for c in brief["why_now"] for i in c["evidence_ids"]}, key=lambda x: int(x[1:]))
    return {
        "AI_Fit_Score__c": decisions["fit_score"],
        "AI_Timing_Score__c": decisions["timing_score"],
        "AI_Priority__c": decisions["priority"],
        "AI_Recommended_Action__c": brief["recommended_action"],
        "AI_Route_To__c": decisions.get("route_to") or decisions.get("owner_team", ""),
        "AI_Brief_Summary__c": brief["summary"],
        "AI_Why_Now__c": "\n".join(f"- {c['text']} [{', '.join(c['evidence_ids'])}]" for c in brief["why_now"]),
        "AI_Product_Angle__c": brief["product_angle"],
        "AI_Flags__c": ";".join(decisions["flags"]),
        "AI_Confidence__c": brief["confidence"],
        "AI_Evidence__c": "\n".join(f"{e['id']}: {e['source']} / {e['field']}" for e in evidence if e["id"] in used),
        "AI_Run_Id__c": run.get("request_id", ""),
        "AI_Generated_At__c": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def to_run_log(run: dict, checks: dict[str, tuple[bool, str]]) -> dict:
    """The AI_Run__c record: cost, checks and prompt version."""
    def passed(names: list[str]) -> int:
        return sum(1 for name in names if checks.get(name, (False, ""))[0])

    return {
        "Run_Id__c": run.get("request_id", ""),
        "Model__c": run.get("served_by") or run.get("model", ""),
        "Prompt_Version__c": run.get("prompt_version", ""),
        "Cost_USD__c": run.get("cost_usd", 0),
        "Latency_Seconds__c": run.get("latency_s", 0),
        "Hard_Checks_Passed__c": passed(HARD),
        "Soft_Checks_Passed__c": passed(SOFT),
        "Live_Checks_Passed__c": passed(LIVE),
    }


def merge_write(existing: dict, payload: dict) -> tuple[dict, list[str]]:
    """Return (fields to update, editable fields skipped because a rep corrected them)."""
    locked = set(filter(None, (existing.get("AI_Locked_Fields__c") or "").split(";")))
    update, skipped = {}, []
    for field, value in payload.items():
        if field not in AI_FIELDS:
            raise ValueError(f"engine tried to write a non-AI field: {field}")
        if field in locked and field in REP_EDITABLE_FIELDS:
            skipped.append(field)
            continue
        if existing.get(field) != value:
            update[field] = value
    return update, skipped
