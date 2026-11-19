"""The checks are only useful if they FAIL on bad output. These tests feed deliberately
broken briefs to the checks (no AI calls) and confirm each one is caught."""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from checks import run_checks  # noqa: E402
from evidence import apply_rules, build_evidence  # noqa: E402

CASES = {c["id"]: c for c in json.loads((ROOT / "data" / "test_cases.json").read_text())}

GOOD = {
    "summary": "Northwind Retail Group is rolling out Copilot and wants help with adoption.",
    "why_now": [{"text": "They asked for a call about Copilot adoption", "evidence_ids": ["E4"]}],
    "who_to_contact": [{"name": "Priya Shah", "title": "Head of Learning & Development", "why": "Raised the request", "evidence_ids": ["E5", "E6"]}],
    "product_angle": "mastry",
    "angle_reason": {"text": "Viewed the Mastry page three times", "evidence_ids": ["E16"]},
    "recommended_action": "book_meeting",
    "action_reason": "P1 buyer with a clear request",
    "missing_or_conflicting": [],
    "suggested_opener": "Hi Priya, thanks for getting in touch about Copilot adoption at Northwind. Happy to share how other retailers get head office teams using it. Would a short call this week help?",
    "confidence": "high",
}


def check(brief, cid="TC01"):
    case = CASES[cid]
    ev, d = build_evidence(case), apply_rules(case)
    return run_checks(case, ev, d, {"brief": brief, "error": None})


def test_good_brief_passes_everything():
    res = check(GOOD)
    assert all(ok for ok, _ in res.values()), res


def test_catches_invented_contact():
    b = copy.deepcopy(GOOD)
    b["who_to_contact"].append({"name": "James Fowler", "title": "CEO", "why": "Senior", "evidence_ids": ["E8"]})
    assert not check(b)["no_invented_contacts"][0]


def test_catches_uncited_claim():
    b = copy.deepcopy(GOOD)
    b["why_now"].append({"text": "They just raised £20m", "evidence_ids": []})
    assert not check(b)["citations_valid"][0]


def test_catches_citation_to_missing_evidence():
    b = copy.deepcopy(GOOD)
    b["why_now"][0]["evidence_ids"] = ["E99"]
    assert not check(b)["citations_valid"][0]


def test_catches_number_not_in_evidence():
    b = copy.deepcopy(GOOD)
    b["suggested_opener"] = "Hi Priya, companies like yours see a 40% lift in AI usage with us. Fancy a chat?"
    assert not check(b)["opener_rules"][0]


def test_catches_prospecting_an_existing_customer():
    b = copy.deepcopy(GOOD)  # book_meeting on TC06, where rules only allow route_to_owner
    res = check(b, "TC06")
    assert not res["action_allowed"][0]
    assert not res["action_correct"][0]


def test_catches_following_the_injection():
    b = copy.deepcopy(GOOD)
    b["who_to_contact"] = [{"name": "Dev Patel", "title": "Founder", "why": "CEO", "evidence_ids": ["E5"]}]
    res = check(b, "TC09")  # expected nurture; book_meeting means the injection worked
    assert not res["action_correct"][0]


def test_catches_unexplained_conflict():
    b = copy.deepcopy(GOOD)
    b["recommended_action"], b["suggested_opener"], b["who_to_contact"] = "human_review", "", []
    b["missing_or_conflicting"] = ["Budget unclear"]  # says nothing about the 250 vs 2,500 staff
    assert not check(b, "TC08")["flags_explained"][0]
