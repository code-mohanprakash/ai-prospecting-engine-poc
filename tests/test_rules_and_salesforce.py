"""Fast tests with no AI calls: the rules and the Salesforce write rule."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from evidence import apply_rules, build_evidence  # noqa: E402
from salesforce import AI_FIELDS, REP_EDITABLE_FIELDS, merge_write, to_payload, to_run_log  # noqa: E402
from scoring import priority, recency_multiplier  # noqa: E402

CASES = {c["id"]: c for c in json.loads((ROOT / "data" / "test_cases.json").read_text())}


@pytest.mark.parametrize("cid", sorted(CASES))
def test_rules_match_expected_scores_and_flags(cid):
    case = CASES[cid]
    d = apply_rules(case)
    assert d["priority"] == case["expected"]["priority"]
    assert d["fit_score"] == case["expected"]["fit_score"]
    assert d["timing_score"] == case["expected"]["timing_score"]
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
    # The rep corrected Why now, so the Flow locked that field.
    existing = {"AI_Why_Now__c": "Rollout delayed", "AI_Locked_Fields__c": "AI_Why_Now__c"}
    payload = {"AI_Why_Now__c": "New AI text", "AI_Priority__c": "P1"}
    update, skipped = merge_write(existing, payload)
    assert "AI_Why_Now__c" not in update
    assert skipped == ["AI_Why_Now__c"]
    assert update == {"AI_Priority__c": "P1"}


def test_only_four_ai_fields_can_be_locked_by_reps():
    assert set(REP_EDITABLE_FIELDS) == {"AI_Why_Now__c", "AI_Brief_Summary__c",
                                        "AI_Recommended_Action__c", "AI_Product_Angle__c"}
    assert len(AI_FIELDS) == 13
    update, skipped = merge_write({"AI_Locked_Fields__c": "AI_Priority__c"}, {"AI_Priority__c": "P1"})
    assert update == {"AI_Priority__c": "P1"}
    assert skipped == []


def test_slide_scoring_example():
    d = apply_rules(CASES["TC04"])
    assert (d["fit_score"], d["timing_score"], d["priority"], d["score"]) == (70, 70, "P1", 70)


def test_recency_and_priority_rules():
    assert [recency_multiplier(n) for n in (0, 30, 31, 90, 91)] == [1.0, 1.0, 0.5, 0.5, 0.0]
    assert [priority(*pair) for pair in ((50, 50), (49, 50), (50, 49), (49, 49), (None, 90))] == \
        ["P1", "P2", "P3", "P4", "Unscored"]


def test_recent_disqualification_caps_timing():
    case = json.loads(json.dumps(CASES["TC01"]))
    case["scoring"]["recently_disqualified"] = True
    assert apply_rules(case)["timing_score"] == 20


def test_config_controls_which_tools_run():
    case = CASES["TC06"]
    assert any(e["source"] == "Gong" for e in build_evidence(case))
    assert not any(e["source"] == "Gong" for e in build_evidence(case, ["salesforce_context", "web_evidence"]))


def test_run_log_keeps_cost_checks_and_prompt_version():
    checks = {"valid_output": (True, ""), "citations_valid": (True, ""), "flags_explained": (False, "")}
    log = to_run_log({"request_id": "req_1", "prompt_version": "v3", "cost_usd": 0.03}, checks)
    assert log["Prompt_Version__c"] == "v3"
    assert log["Cost_USD__c"] == 0.03
    assert log["Hard_Checks_Passed__c"] == 2


def test_record_gets_facts_not_draft_or_prompt_version():
    brief = {"why_now": [{"text": "Hiring a Digital Skills Lead", "evidence_ids": ["E1"]}],
             "recommended_action": "contact_now", "summary": "s", "product_angle": "a",
             "suggested_opener": "Hi Helen...", "confidence": "high"}
    decisions = {"fit_score": 70, "timing_score": 70, "priority": "P1", "flags": [], "route_to": "SDR"}
    run = {"prompt_version": "v3", "request_id": "req_123"}
    payload = to_payload(decisions, brief, [{"id": "E1", "source": "Floqer", "field": "job_post"}], run)
    assert not any("Opener" in f or "Prompt_Version" in f for f in payload)
    assert payload["AI_Run_Id__c"] == "req_123"  # the link to the run log, which has the prompt version
    for field in ("AI_Suggested_Opener__c", "AI_Prompt_Version__c"):
        with pytest.raises(ValueError):
            merge_write({}, {field: "x"})


def test_engine_cannot_write_rep_fields():
    with pytest.raises(ValueError):
        merge_write({}, {"Status": "Qualified"})
