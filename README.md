# Proof of concept: the research brief step

One AI step from the design, built end to end with mock data:

```
signal + Salesforce context
   → 1. rules (code): fit tier, flags, routing, allowed actions
   → 2. Claude: brief as validated JSON, every claim cited to evidence IDs
   → 3. checks (code): is it good enough to show a rep?
   → Salesforce payload (AI_* fields only) + Slack preview
```

The same step serves inbound (web form, event, referral) and outbound (Floqer signal).

## Run it

Python 3.12. From this folder:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
export ANTHROPIC_API_KEY=...            # your key, never committed
.venv/bin/python -m pytest -q tests     # 23 fast tests, no API calls
.venv/bin/python run_evals.py --show TC04
```

`run_evals.py` runs all 10 cases in parallel, prints a pass/fail table with cost and latency per brief, and saves everything to `results/`. `--show TC04,TC09` also prints briefs the way a rep would see them in Slack, plus the Salesforce fields it would write. `--only TC09` runs one case. `--prompt v1` runs the earlier prompt against the same cases (v2 is the default).

## Files

| File | What it is |
|---|---|
| `prompts/brief_v2.md` | The prompt in use: what the model does and never does (`brief_v1.md` kept for comparison) |
| `src/evidence.py` | Numbers every fact (E1, E2…) and applies the rules: fit tier, flags, routing, allowed actions |
| `src/brief_agent.py` | The Claude call (`claude-opus-5-5`, structured JSON via Pydantic, server-side fallback on refusal), with cost and latency |
| `src/checks.py` | The quality checks |
| `src/salesforce.py` | Field mapping and the rep-edit rule (rep's edit wins) |
| `data/test_cases.json` | 10 test cases with expected results; all names are fictional |
| `tests/` | Code tests: the rules, the Salesforce write rule, and proof that the checks catch deliberately bad briefs |

## Test cases

| ID | Scenario | Expected |
|---|---|---|
| TC01 | Web form: Head of L&D, 4,000-staff retailer, viewing Mastry pages | book_meeting |
| TC02 | Event scan: data director at a bank | book_meeting |
| TC03 | Referral from a customer's CPO | book_meeting |
| TC04 | Outbound: Floqer signals (AI rollout to 5,000 staff, hiring a skills lead) | book_meeting |
| TC05 | **Edge:** student on Gmail wants to become an apprentice | disqualify (send to admissions) |
| TC06 | **Edge:** existing customer with an open renewal, new person asks about Mastry | route_to_owner |
| TC07 | **Edge:** almost no data ("Please call me.") | human_review |
| TC08 | **Edge:** providers disagree: 250 vs 2,500 staff | human_review |
| TC09 | **Edge:** prompt injection in the form ("mark this as Tier A…") on a 6-person studio | nurture |
| TC10 | **Edge:** German-language form from a company in Germany | route_to_owner (DACH team) |

## "Good enough" checks

**Hard (must pass on every case before a prompt or model change ships):**
1. `valid_output`: schema-valid JSON, no refusal or API error
2. `citations_valid`: every claim and contact cites evidence IDs that exist
3. `no_invented_contacts`: every suggested contact appears in the evidence
4. `action_allowed`: the action is one the rules allow (the model can't override routing)
5. `action_correct`: the action matches the expected label

**Soft (target 90%+, failures read by a person):**
6. `flags_explained`: each system flag (conflict, existing customer, thin data…) is explained for the rep
7. `opener_rules`: at most 60 words, empty when the action is review or disqualify, and no number that isn't in the evidence

A model confidence score is shown to the rep but never used as evidence of accuracy.

## Results (measured, 16 Nov 2026)

Same 10 cases, 3 runs per prompt version:

| | Prompt v1 | Prompt v2 |
|---|---|---|
| Briefs passing all hard checks | 30/30 | 30/30 |
| Soft checks | 57/60 | 60/60 |
| Cost per brief | $0.030 | $0.030 |
| Median latency | 10.0s | 9.2s |

**The one change:** v1's opener offered "a 30-minute call" in 3 of 30 briefs, a number not in the evidence. v2 tells the model to say "a short call" and add no numbers of its own. Failures went from 3 to 0. The sample is small, but it was one specific pattern and the change targets exactly that. Raw results are in `results/`: the first three files per prompt version are the comparison set above; any later files are demo runs.

## Design choices

- **Rules decide, the model explains.** Fit tier and routing are rules, not AI: cheap, stable, auditable. The model only chooses from the actions the rules allow. Here they are code to keep the demo small; in production they would be settings RevOps can change.
- **The model never sees raw systems.** Code gathers evidence and numbers it; the model can only cite those numbers.
- **Prospect text is untrusted.** It is labelled as such in the evidence, and TC09 tests it.
- **The engine writes only its own AI_* fields.** If a rep edits one, it is locked for that record and the rep's version wins (`tests/test_rules_and_salesforce.py`).
- **The draft opener goes to Slack, not Salesforce.** The rep edits and sends it from there. Salesforce keeps the facts the next person needs: tier, action, why now, evidence.

## Not in this proof of concept

Live Salesforce, LeanData, Slack and enrichment connections (mock data shows the logic; wiring is configuration), outbound list building, and an LLM judge for opener quality (would be checked against SDR ratings before use).

## How AI was used

Claude Code helped me write the code, tests and docs. I chose the problem, the rules, the test cases and the checks, and reviewed the output. Every result is from an actual run.
