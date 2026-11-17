"""Step 3 (code): automatic checks that decide whether a brief is good enough to show a rep.

HARD checks must pass on every case before a prompt or model change ships.
SOFT checks are quality signals; we track the pass rate and review failures by hand.
"""

from __future__ import annotations

import json
import re

HARD = ["valid_output", "citations_valid", "no_invented_contacts", "action_allowed", "action_correct"]
SOFT = ["flags_explained", "opener_rules"]

FLAG_WORDS = {
    "personal_email": ["personal", "gmail", "email"],
    "thin_data": ["unknown", "missing", "no ", "not "],
    "conflicting_employee_count": ["employee", "size", "headcount", "250"],
    "existing_customer": ["customer", "renewal", "opportunity", "owner"],
    "dach_region": ["german", "dach", "germany"],
}


def _all_claims(brief: dict) -> list[dict]:
    return list(brief["why_now"]) + [brief["angle_reason"]] + list(brief["who_to_contact"])


def run_checks(case: dict, evidence: list[dict], decisions: dict, result: dict) -> dict[str, tuple[bool, str]]:
    out: dict[str, tuple[bool, str]] = {}
    brief = result.get("brief")
    if not brief:
        out["valid_output"] = (False, result.get("error") or "no output")
        return out
    out["valid_output"] = (True, "schema-valid JSON")

    # Every claim cites at least one evidence ID, and every ID exists.
    ids = {e["id"] for e in evidence}
    bad = [c for c in _all_claims(brief) if not c["evidence_ids"] or not set(c["evidence_ids"]) <= ids]
    out["citations_valid"] = (not bad, "all claims cited" if not bad else f"{len(bad)} uncited/unknown-ID claims")

    # Contacts must be people who appear in the evidence (no made-up names).
    ev_text = json.dumps(evidence, ensure_ascii=False).lower()
    invented = [c["name"] for c in brief["who_to_contact"]
                if not all(part.lower() in ev_text for part in c["name"].split())]
    out["no_invented_contacts"] = (not invented, "ok" if not invented else f"not in evidence: {invented}")

    action = brief["recommended_action"]
    out["action_allowed"] = (action in decisions["allowed_actions"],
                             f"{action} (allowed: {decisions['allowed_actions']})")
    expected = case["expected"]["action"]
    out["action_correct"] = (action == expected, f"got {action}, expected {expected}")

    # Each system flag is explained in plain words for the rep.
    notes = " ".join(brief["missing_or_conflicting"]).lower()
    missing = [f for f in decisions["flags"] if not any(w in notes for w in FLAG_WORDS.get(f, [f]))]
    out["flags_explained"] = (not missing, "ok" if not missing else f"not explained: {missing}")

    # Opener: empty when it should be, short, and no numbers that aren't in the evidence.
    opener = brief["suggested_opener"].strip()
    problems = []
    if action in ("disqualify", "human_review"):
        if opener:
            problems.append("opener should be empty")
    else:
        if not opener:
            problems.append("missing opener")
        if len(opener.split()) > 60:
            problems.append(f"{len(opener.split())} words > 60")
        for num in re.findall(r"\d[\d,]*", opener):
            if num.replace(",", "") not in ev_text.replace(",", ""):
                problems.append(f"number {num} not in evidence")
    out["opener_rules"] = (not problems, "ok" if not problems else "; ".join(problems))
    return out
