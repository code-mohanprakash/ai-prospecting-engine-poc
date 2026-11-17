"""Run the research-brief step on every test case and score it.

Usage:
  python run_evals.py                 # all 10 cases, table + results/report.md
  python run_evals.py --show TC04     # also print one brief as a rep sees it
  python run_evals.py --only TC09     # one case
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from brief_agent import write_brief  # noqa: E402
from checks import HARD, SOFT, run_checks  # noqa: E402
from evidence import apply_rules, build_evidence  # noqa: E402
from salesforce import merge_write, to_payload  # noqa: E402


def run_case(client, case, prompt_version):
    evidence = build_evidence(case)
    decisions = apply_rules(case)
    result = write_brief(client, evidence, decisions, prompt_version)
    checks = run_checks(case, evidence, decisions, result)
    return {"case": case, "evidence": evidence, "decisions": decisions, "result": result, "checks": checks}


def slack_preview(r: dict) -> str:
    c, d, b = r["case"], r["decisions"], r["result"]["brief"]
    lead = c["lead"]
    lines = [
        "─" * 72,
        f"#inbound-briefs  ·  {lead.get('first_name','')} {lead.get('last_name','')}, {lead.get('title') or 'title unknown'} @ {lead.get('company') or 'company unknown'}",
        f"Fit: {d['fit_tier']}   Action: {b['recommended_action'].upper()}   Confidence: {b['confidence']}   Angle: {b['product_angle']}",
    ]
    if d.get("route_to"):
        lines.append(f"Routed to: {d['route_to']}")
    lines += ["", b["summary"], "", "Why now:"]
    lines += [f"  • {w['text']}  [{', '.join(w['evidence_ids'])}]" for w in b["why_now"]] or ["  • nothing specific"]
    if b["who_to_contact"]:
        lines += ["Who:"] + [f"  • {p['name']}, {p['title']}: {p['why']}  [{', '.join(p['evidence_ids'])}]" for p in b["who_to_contact"]]
    if b["missing_or_conflicting"]:
        lines += ["Check first:"] + [f"  ⚠ {m}" for m in b["missing_or_conflicting"]]
    if b["suggested_opener"]:
        lines += ["", "Suggested opener:", f"  \"{b['suggested_opener']}\""]
    lines += ["", "Sources:"] + [f"  {e['id']}: {e['source']} / {e['field']}" for e in r["evidence"]]
    lines += ["[ 👍 Useful ]  [ 👎 Wrong ]  [ ✏️ Edit in Salesforce ]", "─" * 72]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="run one case id, e.g. TC09")
    ap.add_argument("--show", help="print briefs as a rep sees them, e.g. TC04 or TC04,TC09")
    ap.add_argument("--prompt", default="v2", help="prompt version in prompts/brief_<v>.md")
    args = ap.parse_args()

    cases = json.loads((ROOT / "data" / "test_cases.json").read_text())
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    print(f"Running {len(cases)} cases on prompt {args.prompt} ...\n")
    with ThreadPoolExecutor(max_workers=5) as pool:
        runs = list(pool.map(lambda c: run_case(client, c, args.prompt), cases))

    cols = HARD + SOFT
    short = {"valid_output": "valid", "citations_valid": "cited", "no_invented_contacts": "no-invent",
             "action_allowed": "allowed", "action_correct": "action", "flags_explained": "flags", "opener_rules": "opener"}
    header = f"{'case':<5} {'kind':<10} " + " ".join(f"{short[c]:<9}" for c in cols) + "  action (got / expected)        s     $"
    print(header)
    print("-" * len(header))
    hard_fail = 0
    soft_pass = soft_total = 0
    for r in runs:
        ch, res = r["checks"], r["result"]
        cells = []
        for c in cols:
            ok = ch.get(c, (False, "not run"))[0]
            cells.append(f"{'PASS' if ok else 'FAIL':<9}")
        if not all(ch.get(c, (False,))[0] for c in HARD):
            hard_fail += 1
        for c in SOFT:
            soft_total += 1
            soft_pass += ch.get(c, (False,))[0]
        got = res["brief"]["recommended_action"] if res.get("brief") else "ERROR"
        print(f"{r['case']['id']:<5} {r['case']['kind'][:10]:<10} " + " ".join(cells)
              + f"  {got:<14} / {r['case']['expected']['action']:<14} {res.get('latency_s', 0):>5} {res.get('cost_usd', 0):>6}")

    n = len(runs)
    costs = [r["result"].get("cost_usd", 0) for r in runs]
    lat = sorted(r["result"].get("latency_s", 0) for r in runs)
    print("\nSummary")
    print(f"  Hard checks: {n - hard_fail}/{n} cases pass all hard checks  (ship bar: {n}/{n})")
    print(f"  Soft checks: {soft_pass}/{soft_total} pass  (target: 90%+, failures reviewed by hand)")
    print(f"  Cost: ${sum(costs):.3f} total, ${sum(costs)/n:.4f} per brief (measured from token usage)")
    print(f"  Latency: median {lat[n//2]}s, max {lat[-1]}s per brief")
    errors = [r for r in runs if r["result"].get("error")]
    if errors:
        print(f"  API/model errors: {[(r['case']['id'], r['result']['error']) for r in errors]}")

    fails = [(r["case"]["id"], c, msg) for r in runs for c, (ok, msg) in r["checks"].items() if not ok]
    if fails:
        print("\nFailures to inspect:")
        for cid, c, msg in fails:
            print(f"  {cid} {c}: {msg}")

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    saved = []
    for r in runs:
        payload = to_payload(r["decisions"], r["result"]["brief"], r["evidence"], r["result"]) if r["result"].get("brief") else None
        saved.append({"id": r["case"]["id"], "title": r["case"]["title"], "decisions": r["decisions"],
                      "run": {k: v for k, v in r["result"].items() if k != "brief"}, "brief": r["result"].get("brief"),
                      "checks": {k: {"pass": ok, "detail": msg} for k, (ok, msg) in r["checks"].items()},
                      "salesforce_update": merge_write({}, payload)[0] if payload else None})
    (out / f"results-{args.prompt}-{stamp}.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2))
    print(f"\nSaved: results/results-{args.prompt}-{stamp}.json")

    if args.show:
        show = {s.strip() for s in args.show.split(",")}
        for r in runs:
            if r["case"]["id"] in show and r["result"].get("brief"):
                print(f"\n\n### {r['case']['id']}: {r['case']['title']}")
                print("\n" + slack_preview(r))
                payload = to_payload(r["decisions"], r["result"]["brief"], r["evidence"], r["result"])
                print("\nSalesforce update (AI_* fields only):")
                for k, v in payload.items():
                    print(f"  {k}: {str(v)[:90]}")
    return 0 if hard_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
