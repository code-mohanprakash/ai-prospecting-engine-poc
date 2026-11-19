"""Clear terminal views for the live demo.

Use the Makefile:
  make all | make inbound | make outbound | make safety | make real
  make search, then make brief (add COMPANY="Tesco" DOMAIN=tesco.com for another company)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import anthropic  # noqa: E402

from brief_agent import write_brief  # noqa: E402
from checks import HARD, LIVE, SOFT, run_checks  # noqa: E402
from evidence import apply_rules, build_evidence  # noqa: E402
from salesforce import REP_EDITABLE_FIELDS, to_payload, to_run_log  # noqa: E402
from live_case import MANDS_DOMAIN, SEARCH_FILE, build_case, normalize_domain  # noqa: E402
from web_research import research_company  # noqa: E402

WIDTH = min(shutil.get_terminal_size((100, 30)).columns, 100)
COLOR = sys.stdout.isatty()
VIEWS = {"inbound": "TC01", "outbound": "TC04", "safety": "TC09"}
CASE_NAMES = {
    "TC01": "Inbound form, large retailer", "TC02": "Inbound event, bank data leader",
    "TC03": "Inbound customer referral", "TC04": "Outbound Floqer signal",
    "TC05": "Student using Gmail", "TC06": "Existing customer",
    "TC07": "Too little data", "TC08": "Company size conflict",
    "TC09": "Prompt injection", "TC10": "German-language lead",
}
CHECK_NAMES = {
    "valid_output": "Correct output format",
    "citations_valid": "Every claim has a source",
    "no_invented_contacts": "No invented people",
    "action_allowed": "Action allowed by the rules",
    "action_correct": "Matches expected answer (test set only)",
    "flags_explained": "Warnings explained",
    "opener_rules": "Draft message follows the rules",
}
FIELD_NAMES = {
    "AI_Fit_Score__c": "Fit score",
    "AI_Timing_Score__c": "Timing score",
    "AI_Priority__c": "Priority",
    "AI_Recommended_Action__c": "Recommended action",
    "AI_Route_To__c": "Route to",
    "AI_Brief_Summary__c": "Summary",
    "AI_Why_Now__c": "Why now",
    "AI_Product_Angle__c": "Product angle",
    "AI_Flags__c": "System flags",
    "AI_Confidence__c": "Confidence",
    "AI_Evidence__c": "Evidence used",
    "AI_Run_Id__c": "Run ID",
    "AI_Generated_At__c": "Created at",
}


def style(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def title(text: str) -> None:
    print("\n" + style("=" * WIDTH, "2"))
    print(style(text, "1"))
    print(style("=" * WIDTH, "2"))


def step(text: str) -> None:
    print("\n" + style(text, "1;36"))


def line(label: str, value) -> None:
    if value in (None, "", [], {}):
        return
    prefix = f"  {label + ':':<18}"
    print(textwrap.fill(str(value), WIDTH, initial_indent=prefix, subsequent_indent=" " * len(prefix)))


def bullet(text: str, mark: str = "-") -> None:
    print(textwrap.fill(str(text), WIDTH, initial_indent=f"  {mark} ", subsequent_indent="    "))


def load_cases() -> dict:
    return {c["id"]: c for c in json.loads((ROOT / "data" / "test_cases.json").read_text())}


def real_evidence(case: dict) -> list[dict]:
    evidence = build_evidence(case)
    for item in evidence:
        if item["source"] == "Salesforce Lead":
            item["source"] = "Research target (not from Salesforce)"

    def add(source: str, field: str, value) -> None:
        evidence.append({"id": f"E{len(evidence) + 1}", "source": source, "field": field, "value": value})

    for public in case["public_facts"]:
        value = {"fact": public["fact"], "url": public["url"]}
        if public.get("published"):
            value["published"] = public["published"]
        if public.get("page_age"):
            value["page_last_updated"] = public["page_age"]
        add(f"Public web ({public['source']})", "verified_fact", value)
    for note in case["system_notes"]:
        add("System note", "research_context", note)
    return evidence


def placeholder(case: dict, evidence: list[dict], decisions: dict) -> dict:
    action = case.get("expected", {}).get("action", "human_review")
    source = evidence[-1]["id"]
    empty = action in ("disqualify", "human_review")
    return {
        "brief": {
            "summary": "DRY RUN placeholder. Claude was not called.",
            "why_now": [{"text": "DRY RUN placeholder.", "evidence_ids": [source]}],
            "who_to_contact": [],
            "product_angle": "unclear",
            "angle_reason": {"text": "DRY RUN placeholder.", "evidence_ids": [source]},
            "recommended_action": action,
            "action_reason": "DRY RUN placeholder.",
            "missing_or_conflicting": [f"{flag.replace('_', ' ')} missing dach" for flag in decisions["flags"]],
            "suggested_opener": "" if empty else "Hi, this is a dry run.",
            "confidence": "low",
        },
        "error": None, "model": "none", "prompt_version": "dry-run", "latency_s": 0, "cost_usd": 0,
    }


def run(client, case: dict, dry_run: bool, real: bool = False) -> dict:
    evidence = real_evidence(case) if real else build_evidence(case)
    decisions = apply_rules(case)
    result = placeholder(case, evidence, decisions) if dry_run else write_brief(client, evidence, decisions)
    scored = case
    if real:
        brief = result.get("brief") or {}
        scored = {**case, "expected": {"action": brief.get("recommended_action", "")}}
    checks = run_checks(scored, evidence, decisions, result)
    if real:
        checks.pop("action_correct", None)
    return {"case": case, "evidence": evidence, "decisions": decisions, "result": result, "checks": checks}


def show_input(case: dict, real: bool) -> None:
    lead, signal = case.get("lead") or {}, case["signal"]
    step("1. WHAT WENT IN")
    line("Data type", "Real public information" if real else "Mock test data with fictional names")
    line("Signal", signal.get("source"))
    line("Received", (signal.get("received_at") or "")[:10])
    line("Prospect message", signal.get("message"))
    person = " ".join(p for p in [lead.get("first_name"), lead.get("last_name")] if p)
    line("Person", ", ".join(p for p in [person, lead.get("title")] if p) or "No named contact")
    line("Company", lead.get("company"))
    line("Country", lead.get("country"))
    for provider, data in (case.get("enrichment") or {}).items():
        if data:
            line(provider.title() if len(provider) < 16 else "Company data", ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in data.items()))
    for item in case.get("floqer_signals") or []:
        line("Floqer signal", item)
    for item in case.get("public_facts") or []:
        line("Public fact", item["fact"])


def show_rules(decisions: dict) -> None:
    step("2. WHAT THE RULES DECIDED (NO AI)")
    fit = decisions["fit_score"] if decisions["fit_score"] is not None else "Not scored"
    score = decisions["score"] if decisions["score"] is not None else "Not scored"
    line("Priority", decisions["priority"])
    line("Overall score", score)
    line("Fit score", fit)
    line("Timing score", decisions["timing_score"])
    line("Route to", decisions.get("route_to") or decisions.get("owner_team"))
    line("Allowed actions", ", ".join(decisions["allowed_actions"]))
    line("System flags", ", ".join(decisions["flags"]) or "None")


def show_brief(brief: dict, evidence: list[dict]) -> None:
    step("3. WHAT CLAUDE WROTE")
    line("Recommendation", brief["recommended_action"].replace("_", " ").upper())
    line("Reason", brief["action_reason"])
    line("Product angle", brief["product_angle"])
    line("Summary", brief["summary"])
    print("\n  Why now:")
    for item in brief["why_now"]:
        bullet(f"{item['text']} [{', '.join(item['evidence_ids'])}]")
    if brief["who_to_contact"]:
        print("\n  Who to contact:")
        for person in brief["who_to_contact"]:
            bullet(f"{person['name']}, {person['title']}: {person['why']} [{', '.join(person['evidence_ids'])}]")
    if brief["missing_or_conflicting"]:
        print("\n  Check first:")
        for item in brief["missing_or_conflicting"]:
            bullet(item, "!")
    print("\n  Draft message:")
    bullet(brief["suggested_opener"] or "None. A person should review this first.")
    used = {i for c in brief["why_now"] + [brief["angle_reason"]] + brief["who_to_contact"] for i in c["evidence_ids"]}
    print("\n  Sources used:")
    for item in evidence:
        if item["id"] in used:
            value = item["value"]
            detail = value["fact"] + " " + value["url"] if isinstance(value, dict) and "fact" in value else value
            bullet(f"{item['id']} {item['source']}: {detail}")


def show_checks(checks: dict) -> None:
    step("4. WHAT THE CODE CHECKED")
    for name, (ok, detail) in checks.items():
        mark = style("PASS", "32") if ok else style("FAIL", "31")
        suffix = "" if ok else f" ({detail})"
        print(f"  {mark}  {CHECK_NAMES[name]}{suffix}")
    if not all(ok for ok, _ in checks.values()):
        print("\n  A person should review the failed check before using this brief.")


def show_salesforce(run_data: dict) -> None:
    result = run_data["result"]
    payload = to_payload(run_data["decisions"], result["brief"], run_data["evidence"], result)
    step("5. WHAT WOULD BE SAVED IN SALESFORCE")
    print("  This demo does not write to a real Salesforce org.\n")
    for field, value in payload.items():
        shown = " ".join(str(value if value not in (None, "") else "Blank").split())
        shown = shown if len(shown) <= 62 else shown[:59] + "..."
        access = "rep can edit" if field in REP_EDITABLE_FIELDS else "read-only"
        print(f"  {FIELD_NAMES[field]:<20} {shown}  ({access})")
    print("\n  Draft message: stays in Slack, not on the Salesforce record.")
    log = to_run_log(result, run_data["checks"])
    print("\n  Run log (AI_Run__c):")
    line("Model", log["Model__c"])
    line("Prompt", log["Prompt_Version__c"])
    line("Cost", f"${log['Cost_USD__c']}")
    line("Time", f"{log['Latency_Seconds__c']} seconds")
    line("Live checks", f"{log['Live_Checks_Passed__c']} of {len(LIVE)} passed")


def show_one(run_data: dict, heading: str, real: bool = False) -> int:
    title(heading)
    if real:
        company = (run_data["case"].get("lead") or {}).get("company") or "this company"
        print("Real public facts only. No Multiverse, Salesforce or Gong data was used.")
        print(f"This is not a claim that {company} is a prospect or customer.")
    show_input(run_data["case"], real)
    show_rules(run_data["decisions"])
    brief = run_data["result"].get("brief")
    if not brief:
        print(f"\nClaude did not return a brief: {run_data['result'].get('error')}")
        return 1
    show_brief(brief, run_data["evidence"])
    show_checks(run_data["checks"])
    show_salesforce(run_data)
    print()
    return 0 if all(run_data["checks"][c][0] for c in HARD if c in run_data["checks"]) else 1


def show_research(found: dict, domain: str) -> None:
    step("WHAT CLAUDE SEARCHED")
    line("Allowed site", f"{domain} only")
    line("Searches run", " | ".join(q for q in found["queries"] if q) or "None")
    line("Pages found", found["pages"])
    if found.get("error"):
        line("Search problem", found["error"])
    step("WHAT THE CODE CHECKED, FACT BY FACT")
    print(f"  A fact passes only if its link is on {domain}, the link came back from the search,")
    print("  and the API attached a quote from that page.\n")
    for fact in found["facts"]:
        print(textwrap.fill(fact["fact"], WIDTH, initial_indent=f"  {style('PASS', '32')}  ", subsequent_indent=" " * 8))
        print(style(f"        {fact['url']}" + (f"  (page date: {fact['page_age']})" if fact.get("page_age") else ""), "2"))
    for fact in found["rejected"]:
        print(textwrap.fill(fact["fact"], WIDTH, initial_indent=f"  {style('FAIL', '31')}  ", subsequent_indent=" " * 8))
        print(style(f"        {', '.join(fact['reasons'])}: {fact['url']}", "2"))
    if not found["facts"] and not found["rejected"]:
        print("  No facts came back.")
    step("CALL 1 COST AND TIME")
    line("Cost", f"${found['cost_usd']} ({found['searches']} searches)")
    line("Time", f"{found['latency_s']} seconds")


def resolve_target(args) -> dict:
    """Company to research. With nothing set, it is Marks & Spencer."""
    company, domain = (args.company or "").strip(), (args.domain or "").strip()
    if not company and not domain:
        company, domain = "Marks & Spencer", MANDS_DOMAIN
    elif not company or not domain:
        raise SystemExit('Set both COMPANY and DOMAIN, for example: make search COMPANY="Tesco" DOMAIN=tesco.com')
    try:
        domain = normalize_domain(domain)
    except ValueError as e:
        raise SystemExit(str(e))
    employees = (args.employees or "").replace(",", "").strip()
    if employees and not employees.isdigit():
        raise SystemExit("EMPLOYEES must be a number, for example EMPLOYEES=330000")
    return {"company": company, "domain": domain, "industry": (args.industry or "").strip() or None,
            "employees": int(employees) if employees else None, "country": (args.country or "").strip() or None}


def run_search(client, args, dry_run: bool) -> int:
    target = resolve_target(args)
    title(f"CALL 1: CLAUDE SEARCHES THE WEB FOR {target['company'].upper()}")
    print(f"Claude can search only {target['domain']}. It finds pages and writes short facts.")
    print("Claude only finds and quotes here. Code then checks every fact before it can be used.")
    if dry_run:
        saved = json.loads((ROOT / "data" / "real_example.json").read_text())["public_facts"]
        facts = [{**f, "page_age": None} for f in saved] if target["domain"] == MANDS_DOMAIN else []
        found = {"facts": facts, "rejected": [], "queries": ["(dry run, no search)"], "pages": len(facts),
                 "error": None, "latency_s": 0, "cost_usd": 0, "searches": 0}
    else:
        print("\nSearching. This takes about 10 to 40 seconds...")
        found = research_company(client, target["company"], [target["domain"]], date.today().isoformat())
    show_research(found, target["domain"])
    if dry_run:
        print("\n  Dry run: nothing saved.\n")
        return 0
    SEARCH_FILE.parent.mkdir(exist_ok=True)
    saved_at = datetime.now().strftime("%H:%M")
    SEARCH_FILE.write_text(json.dumps({**target, "date": date.today().isoformat(), "saved_at": saved_at, **found},
                                      indent=1, ensure_ascii=False))
    print(f"\n  Saved {len(found['facts'])} checked facts for {target['company']}. Next, run: make brief\n")
    return 0


def run_brief(client, dry_run: bool) -> int:
    if not SEARCH_FILE.exists():
        print("No search saved yet. Run make search first.")
        return 0
    search = json.loads(SEARCH_FILE.read_text())
    case = build_case(search)
    company = search["company"]
    print(f"Using the search for {company} saved at {search.get('saved_at', '?')}.")
    if not search["facts"]:
        print("No web facts passed the checks" + (", so the saved M&S facts are used." if search["domain"] == MANDS_DOMAIN
                                                  else ". Claude writes from the company name and notes only."))
    print(f"Call 2: Claude writes the brief from {len(case['public_facts'])} checked facts, with no web access. "
          "This takes about 10 to 15 seconds...")
    run_data = run(client, case, dry_run, real=True)
    code = show_one(run_data, f"CALL 2: CLAUDE WRITES THE BRIEF FOR {company.upper()}", real=True)
    call_2 = run_data["result"].get("cost_usd") or 0
    step("BOTH CALLS")
    line("Call 1 search", f"${search['cost_usd']}")
    line("Call 2 brief", f"${call_2}")
    line("Total", f"${search['cost_usd'] + call_2:.4f}")
    print()
    return code


def show_all(client, cases: dict, dry_run: bool) -> int:
    print(f"Running {len(cases)} mock cases. This takes about 15 to 30 seconds...")
    with ThreadPoolExecutor(max_workers=5) as pool:
        runs = list(pool.map(lambda c: run(client, c, dry_run), cases.values()))
    title("ALL 10 MOCK TEST CASES")
    print(f"{'Case':<5} {'What it tests':<38} {'Expected':<15} {'Claude chose':<15} {'Checks':<7} {'Sec':>5} {'Cost':>7}")
    print("-" * min(WIDTH, 98))
    hard = soft = 0
    problems = []
    for item in runs:
        case, result, checks = item["case"], item["result"], item["checks"]
        name = CASE_NAMES[case["id"]]
        chosen = result["brief"]["recommended_action"] if result.get("brief") else "ERROR"
        passed = sum(1 for ok, _ in checks.values() if ok)
        hard += all(checks.get(c, (False, ""))[0] for c in HARD)
        soft += sum(1 for c in SOFT if checks.get(c, (False, ""))[0])
        problems += [f"{case['id']}: {CHECK_NAMES[c]} ({detail})" for c, (ok, detail) in checks.items() if not ok]
        print(f"{case['id']:<5} {name:<38} {case['expected']['action']:<15} {chosen:<15} "
              f"{passed}/{len(HARD) + len(SOFT):<5} {result.get('latency_s', 0):>5} ${result.get('cost_usd', 0):<6}")
    step("WHAT THIS MEANS")
    costs = [r["result"].get("cost_usd", 0) for r in runs]
    times = [r["result"].get("latency_s", 0) for r in runs]
    line("Must-pass checks", f"{hard}/{len(runs)} cases passed")
    line("Quality checks", f"{soft}/{len(runs) * len(SOFT)} passed")
    line("Average cost", f"${sum(costs) / len(costs):.4f} to write one brief")
    line("Typical time", f"{statistics.median(times)} seconds per brief")
    if problems:
        print("\n  Needs review:")
        for problem in problems:
            bullet(problem, "!")
    print()
    return 0 if hard == len(runs) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("view", choices=["all", *VIEWS, "real", "search", "brief", "research"])
    parser.add_argument("--company", default="")
    parser.add_argument("--domain", default="")
    parser.add_argument("--industry", default="")
    parser.add_argument("--employees", default="")
    parser.add_argument("--country", default="")
    parser.add_argument("--dry-run", action="store_true", help="test the screens without calling Claude")
    args = parser.parse_args()
    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        print("API key not loaded. Set ANTHROPIC_API_KEY or add it to .env.")
        return 2
    client = None if args.dry_run else anthropic.Anthropic()
    cases = load_cases()
    if args.view == "all":
        return show_all(client, cases, args.dry_run)
    if args.view == "search":
        return run_search(client, args, args.dry_run)
    if args.view == "brief":
        return run_brief(client, args.dry_run)
    if args.view == "research":
        run_search(client, args, args.dry_run)
        return run_brief(client, args.dry_run)
    if args.view == "real":
        case = json.loads((ROOT / "data" / "real_example.json").read_text())
        print("Running the real public example. This takes about 10 to 15 seconds...")
        return show_one(run(client, case, args.dry_run, real=True), "REAL PUBLIC EXAMPLE: MARKS & SPENCER", real=True)
    case = cases[VIEWS[args.view]]
    print(f"Running {case['id']}. This takes about 10 to 15 seconds...")
    return show_one(run(client, case, args.dry_run), f"{case['id']}: {CASE_NAMES[case['id']].upper()}")


if __name__ == "__main__":
    raise SystemExit(main())
