"""Step 4 (code): what gets written to Salesforce, and the rule for when a rep edits it.

The engine only ever writes its own AI_* fields. It never touches rep-owned fields
(Status, Owner, Rating, Description...). If a rep edits an AI_* field, a Salesforce
Flow adds that field name to AI_Locked_Fields__c, and the engine stops writing it:
the rep's version wins, and the override is logged so we can learn from it.

The draft opener is not written to Salesforce. It goes to Slack, where the rep edits
and sends it. Salesforce keeps the facts the next person needs: tier, action, why now.
"""

from __future__ import annotations

from datetime import datetime, timezone

AI_FIELDS = [
    "AI_Fit_Tier__c", "AI_Recommended_Action__c", "AI_Route_To__c", "AI_Brief_Summary__c",
    "AI_Why_Now__c", "AI_Product_Angle__c", "AI_Flags__c",
    "AI_Confidence__c", "AI_Evidence__c", "AI_Run_Id__c", "AI_Generated_At__c",
]
# AI_Run_Id__c links the record to its run log, which holds the prompt version, cost and checks.
# Reps don't need those, so they are not fields on the record.


def to_payload(decisions: dict, brief: dict, evidence: list[dict], run: dict) -> dict:
    """Map one brief to Lead/Account fields. Long text is kept short for the record page."""
    used = sorted({i for c in brief["why_now"] for i in c["evidence_ids"]}, key=lambda x: int(x[1:]))
    return {
        "AI_Fit_Tier__c": decisions["fit_tier"],
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


def merge_write(existing: dict, payload: dict) -> tuple[dict, list[str]]:
    """Return (fields to update, fields skipped because a rep owns them now)."""
    locked = set(filter(None, (existing.get("AI_Locked_Fields__c") or "").split(";")))
    update, skipped = {}, []
    for field, value in payload.items():
        if field not in AI_FIELDS:
            raise ValueError(f"engine tried to write a non-AI field: {field}")
        if field in locked:
            skipped.append(field)
            continue
        if existing.get(field) != value:
            update[field] = value
    return update, skipped
