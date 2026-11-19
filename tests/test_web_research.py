"""Call 1 checks: only facts from the company's own site, returned by the search and quoted, get through."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from web_research import extract, verify  # noqa: E402

DOMAINS = ["marksandspencer.com"]
PRESS = "https://corporate.marksandspencer.com/newsroom/press-releases/copilot"


def reply(*text_blocks):
    """A web search reply shaped like the API's content blocks."""
    return [
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "M&S AI training"}},
        {"type": "web_search_tool_result", "content": [
            {"type": "web_search_result", "url": PRESS, "title": "M&S press release", "page_age": "March 25, 2026"},
            {"type": "web_search_result", "url": "https://news.example.com/m-and-s", "title": "Other site"},
        ]},
        *text_blocks,
    ]


def cited(text, url, quote="M&S is buying 11,000 Copilot licences"):
    return {"type": "text", "text": text,
            "citations": [{"type": "web_search_result_location", "url": url, "title": "t", "cited_text": quote}]}


def run(*blocks):
    queries, found, facts_in, errors = extract(reply(*blocks))
    return queries, verify(facts_in, found, DOMAINS)


def text(t):
    return {"type": "text", "text": t}


def test_good_fact_passes_with_page_date():
    queries, (passed, rejected) = run(cited("- M&S is buying 11,000 Copilot licences.", PRESS))
    assert queries == ["M&S AI training"]
    assert [f["fact"] for f in passed] == ["M&S is buying 11,000 Copilot licences."]
    assert passed[0]["page_age"] == "March 25, 2026" and not rejected


def test_other_site_is_rejected():
    _, (passed, rejected) = run(cited("A news site says something.", "https://news.example.com/m-and-s"))
    assert not passed and rejected[0]["reasons"] == ["not on the company's own site"]


def test_link_claude_typed_is_rejected():
    _, (passed, rejected) = run(cited("A page nobody searched.", "https://corporate.marksandspencer.com/made-up"))
    assert not passed and "link was not returned by the search" in rejected[0]["reasons"]


def test_lookalike_domain_is_rejected():
    _, (passed, rejected) = run(cited("Fake.", "https://marksandspencer.com.evil.example/x"))
    assert not passed and "not on the company's own site" in rejected[0]["reasons"]


def test_uncited_text_and_duplicates_are_ignored():
    _, (passed, _) = run(text("I'll search the M&S site.\n- "),
                         cited("M&S is buying 11,000 Copilot licences", PRESS), text(".\n- "),
                         cited("M&S is buying 11,000 Copilot licences", PRESS), text("."))
    assert [f["fact"] for f in passed] == ["M&S is buying 11,000 Copilot licences."]


def test_part_cited_line_keeps_the_whole_sentence():
    _, (passed, _) = run(text("- In March 2026, "), cited("M&S bought 11,000 Copilot licences", PRESS),
                         text(" for store managers.\n- An uncited line is dropped."))
    assert [f["fact"] for f in passed] == ["In March 2026, M&S bought 11,000 Copilot licences for store managers."]


def test_search_error_is_reported():
    _, _, _, errors = extract([{"type": "web_search_tool_result",
                                "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}}])
    assert errors == ["max_uses_exceeded"]
