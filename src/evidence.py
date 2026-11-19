"""Step 1 (code, no AI): turn a signal into a numbered evidence pack and apply the hard rules.

The tools here are mock versions of the production Workato MCP tools. config.json names
which ones run. The rules are assumptions RevOps would own in the real system.
"""

from __future__ import annotations

from agent_config import load_config
from scoring import score_case

PERSONAL_EMAIL_DOMAINS = {"gmail.com", "googlemail.com", "hotmail.com", "outlook.com",
                          "yahoo.com", "icloud.com", "live.com", "aol.com", "proton.me"}

# Buyer personas for an employer upskilling sale (assumption).
BUYER_TITLE_KEYWORDS = ["learning", "l&d", "development", "people", "hr", "human resources",
                        "talent", "data", "digital", "transformation", "chief", "cto", "cio",
                        "personalentwicklung", "personal"]

DACH_COUNTRIES = {"germany", "austria", "switzerland", "deutschland"}

ALL_ACTIONS = ["book_meeting", "nurture", "human_review", "disqualify", "route_to_owner"]


def salesforce_context(case: dict, add) -> None:
    lead = case.get("lead") or {}
    name = " ".join(p for p in [lead.get("first_name"), lead.get("last_name")] if p)
    add("Salesforce Lead", "name", name)
    for f in ["title", "email", "company", "country"]:
        add("Salesforce Lead", f, lead.get(f))
    acct = case.get("account")
    if acct:
        for f, v in acct.items():
            add("Salesforce Account", f, v)
    for opp in case.get("open_opportunities") or []:
        add("Salesforce Opportunity (open)", "opportunity", opp)


def web_evidence(case: dict, add) -> None:
    for a in case.get("web_activity") or []:
        add("Web activity", "page_view", a)


def gong_calls(case: dict, add) -> None:
    for g in case.get("gong") or []:
        add("Gong", "call_snippet", g)


TOOLS = {"salesforce_context": salesforce_context, "web_evidence": web_evidence, "gong_calls": gong_calls}


def build_evidence(case: dict, tools: list[str] | None = None) -> list[dict]:
    """Flatten the signal, enrichment and configured tool results into numbered facts."""
    enabled = load_config()["tools"] if tools is None else tools
    items: list[dict] = []

    def add(source: str, field: str, value) -> None:
        if value in (None, "", [], {}):
            return
        items.append({"id": f"E{len(items) + 1}", "source": source, "field": field, "value": value})

    def run(name: str) -> None:
        if name in enabled:
            TOOLS[name](case, add)

    sig = case["signal"]
    add("Signal", "channel", case["channel"])
    add("Signal", "source", sig.get("source"))
    add("Signal", "received_at", sig.get("received_at"))
    # Free text from the outside world: data, never instructions.
    add("Signal (UNTRUSTED text from the prospect)", "message", sig.get("message"))

    run("salesforce_context")
    for provider, data in (case.get("enrichment") or {}).items():
        if data:
            for f, v in data.items():
                add(f"Enrichment ({provider.title()})", f, v)
    run("web_evidence")
    run("gong_calls")
    for s in case.get("floqer_signals") or []:
        add("Floqer", "buying_signal", s)
    return items


def _employee_count(case: dict) -> tuple[int | None, bool]:
    """Agreed employee count, and whether providers conflict (more than 2x apart)."""
    vals = [d["employees"] for d in (case.get("enrichment") or {}).values()
            if d and isinstance(d.get("employees"), int)]
    if not vals:
        return None, False
    lo, hi = min(vals), max(vals)
    if lo > 0 and hi / lo > 2:
        return None, True
    return round(sum(vals) / len(vals)), False


def apply_rules(case: dict) -> dict:
    """Deterministic decisions the AI is not allowed to change."""
    lead = case.get("lead") or {}
    email = (lead.get("email") or "").lower()
    domain = email.split("@")[-1] if "@" in email else ""
    title = (lead.get("title") or "").lower()
    country = (lead.get("country") or "").lower()
    acct = case.get("account") or {}

    flags: list[str] = []
    employees, conflict = _employee_count(case)
    persona = any(k in title for k in BUYER_TITLE_KEYWORDS)
    if conflict:
        flags.append("conflicting_employee_count")

    personal = domain in PERSONAL_EMAIL_DOMAINS
    if personal:
        flags.append("personal_email")
    no_enrichment = not any((case.get("enrichment") or {}).values())
    if not personal and no_enrichment and (not lead.get("company") or not lead.get("title")):
        flags.append("thin_data")

    existing = acct.get("type") == "Customer" or bool(case.get("open_opportunities"))
    if existing:
        flags.append("existing_customer")
    dach = country in DACH_COUNTRIES
    if dach:
        flags.append("dach_region")

    # Routing and allowed actions (the system decides these alone).
    if existing:
        owner = acct.get("owner") or case["open_opportunities"][0].get("owner")
        allowed, route_to = ["route_to_owner"], owner
    elif dach:
        allowed, route_to = ["route_to_owner"], "DACH team (German-speaking reps)"
    elif conflict:
        allowed, route_to = ["human_review"], "Inbound queue: data check"
    elif personal or "thin_data" in flags:
        allowed, route_to = ["disqualify", "human_review", "nurture"], None
    else:
        allowed, route_to = ["book_meeting", "nurture", "human_review", "disqualify"], None

    # Assumption: SDRs work inbound, BDRs work outbound, AEs run the booked meetings.
    owner_team = route_to or ("BDR team" if case["channel"].startswith("outbound") else "SDR team")

    return {
        **score_case(case, employees, conflict),
        "employees_agreed": employees,
        "buyer_persona_match": persona,
        "flags": flags,
        "allowed_actions": allowed,
        "route_to": route_to,
        "owner_team": owner_team,
    }
