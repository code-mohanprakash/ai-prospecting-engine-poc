"""Fast tests with no AI calls: the rules and the Salesforce write rule."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from evidence import apply_rules, build_evidence  # noqa: E402
from salesforce import merge_write, to_payload  # noqa: E402

CASES = {c["id"]: c for c in json.loads((ROOT / "data" / "test_cases.json").read_text())}


@pytest.mark.parametrize("cid", sorted(CASES))
def test_rules_match_expected_tier_and_flags(cid):
    case = CASES[cid]
    d = apply_rules(case)
    assert d["fit_tier"] == case["expected"]["fit_tier"]
    for flag in case["expected"]["must_flag"]:
        assert flag in d["flags"]
    assert case["expected"]["action"] in d["allowed_actions"]


def test_existing_customer_is_never_prospected():
    d = apply_rules(CASES["TC06"])
    assert d["allowed_actions"] == ["route_to_owner"]
    assert "Rachel Green" in d["route_to"]


def test_untrusted_text_is_labelled():
    ev = build_evidence(CASES["TC09"])
    msg = [e for e in ev if e["field"] == "message"][0]
    assert "UNTRUSTED" in msg["source"]


def test_rep_edit_wins():
    # Rules said B; the rep knows better and set A, so the Flow locked the field.
    existing = {"AI_Fit_Tier__c": "A", "AI_Locked_Fields__c": "AI_Fit_Tier__c"}
    payload = {"AI_Fit_Tier__c": "B", "AI_Why_Now__c": "New signal"}
    update, skipped = merge_write(existing, payload)
    assert "AI_Fit_Tier__c" not in update
    assert skipped == ["AI_Fit_Tier__c"]
    assert update == {"AI_Why_Now__c": "New signal"}


def test_record_gets_facts_not_draft_or_prompt_version():
    brief = {"why_now": [{"text": "Hiring a Digital Skills Lead", "evidence_ids": ["E1"]}],
             "recommended_action": "contact_now", "summary": "s", "product_angle": "a",
             "suggested_opener": "Hi Helen...", "confidence": "high"}
    decisions = {"fit_tier": "A", "flags": [], "route_to": "SDR"}
    run = {"prompt_version": "v2", "request_id": "req_123"}
    payload = to_payload(decisions, brief, [{"id": "E1", "source": "Floqer", "field": "job_post"}], run)
    assert not any("Opener" in f or "Prompt_Version" in f for f in payload)
    assert payload["AI_Run_Id__c"] == "req_123"  # the link to the run log, which has the prompt version
    for field in ("AI_Suggested_Opener__c", "AI_Prompt_Version__c"):
        with pytest.raises(ValueError):
            merge_write({}, {field: "x"})


def test_engine_cannot_write_rep_fields():
    with pytest.raises(ValueError):
        merge_write({}, {"Status": "Qualified"})
