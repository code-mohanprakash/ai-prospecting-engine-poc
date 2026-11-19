"""Turn a saved call 1 search into a case that the rules and the brief writer (call 2) can use.

make search saves results/last-search.json. make brief reads it and builds the case here.
For Marks & Spencer the saved company data and signal from data/real_example.json are reused.
For any other company, the only company data is what you pass in (INDUSTRY, EMPLOYEES, COUNTRY),
standing in for what Lusha or Cognism would supply in production.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
SEARCH_FILE = ROOT / "results" / "last-search.json"
MANDS_DOMAIN = "marksandspencer.com"
REGIONS = {"united kingdom": "UK", "uk": "UK", "england": "UK", "scotland": "UK", "wales": "UK",
           "northern ireland": "UK", "germany": "DACH", "austria": "DACH", "switzerland": "DACH"}


def normalize_domain(value: str) -> str:
    """'https://www.Tesco.com/about' -> 'tesco.com'. Raises ValueError if it isn't a domain."""
    text = value.strip().lower()
    host = urlparse(text if "://" in text else "https://" + text).hostname or ""
    host = host[4:] if host.startswith("www.") else host
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host):
        raise ValueError(f"'{value}' is not a website domain. Use one like tesco.com")
    return host


def build_case(search: dict) -> dict:
    facts, today, domain = search["facts"], search["date"], search["domain"]
    first_note = f"The research date is {today}. The public facts come from a live search of {domain}."
    if domain == MANDS_DOMAIN:
        case = json.loads((ROOT / "data" / "real_example.json").read_text())
        notes = [first_note, "The rules scored timing from the saved signal dated 2026-03-25, "
                             "so it is background, not a fresh signal.", *case["system_notes"][1:]]
        return {**case, "public_facts": facts or case["public_facts"], "system_notes": notes}

    company = search["company"]
    country = search.get("country") or "United Kingdom"
    details = {k: v for k, v in {"employees": search.get("employees"), "industry": search.get("industry")}.items() if v}
    return {
        "id": "LIVE",
        "title": f"Live public example: {company}",
        "kind": "real_public",
        "channel": "outbound_signal",
        "signal": {"source": "Public web research", "received_at": today},
        "lead": {"first_name": "", "last_name": "", "title": "", "email": "", "company": company, "country": country},
        "account": None,
        "open_opportunities": [],
        "enrichment": {"details given for the demo": details} if details else {},
        "web_activity": [],
        "gong": [],
        "floqer_signals": [],
        "public_facts": facts,
        "system_notes": [
            first_note,
            "Salesforce and Gong are not connected, so past contact, customer status and open deals are unknown.",
            "No Multiverse win-rate history was used, so the fit score starts at 50." if search.get("industry")
            else "No industry was given, so the rules cannot score fit.",
            "There is no form or Floqer signal for this company, so timing is 0.",
        ],
        "scoring": {"region": REGIONS.get(country.lower(), country), "industry": search.get("industry") or "",
                    "use_segment_history": False, "signals": []},
    }
