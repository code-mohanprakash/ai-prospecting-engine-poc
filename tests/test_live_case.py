"""make search / make brief: any company can be researched, and the rules treat it honestly."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evidence import apply_rules  # noqa: E402
from live_case import build_case, normalize_domain  # noqa: E402

FACT = {"fact": "Tesco launched a digital skills academy.", "url": "https://www.tescoplc.com/x", "source": "t"}


def search(**extra):
    return {"company": "Tesco", "domain": "tescoplc.com", "date": "2026-11-19", "facts": [FACT],
            "cost_usd": 0.1, **extra}


@pytest.mark.parametrize("raw, clean", [("tesco.com", "tesco.com"), ("https://www.Tesco.com/about", "tesco.com"),
                                        ("corporate.marksandspencer.com", "corporate.marksandspencer.com")])
def test_domain_is_cleaned(raw, clean):
    assert normalize_domain(raw) == clean


@pytest.mark.parametrize("bad", ["tesco", "not a domain", "", "tesco .com"])
def test_bad_domain_is_refused(bad):
    with pytest.raises(ValueError):
        normalize_domain(bad)


def test_other_company_with_industry_scores_fit_50_and_timing_0():
    decisions = apply_rules(build_case(search(industry="Retail", employees=330000)))
    assert (decisions["fit_score"], decisions["timing_score"], decisions["priority"]) == (50, 0, "P3")


def test_other_company_without_details_is_unscored_and_limited():
    decisions = apply_rules(build_case(search()))
    assert decisions["priority"] == "Unscored"
    assert "book_meeting" not in decisions["allowed_actions"]


def test_small_company_fit_is_halved():
    assert apply_rules(build_case(search(industry="Retail", employees=120)))["fit_score"] == 25


def test_mands_keeps_saved_company_data_and_uses_live_facts():
    case = build_case({"company": "Marks & Spencer", "domain": "marksandspencer.com", "date": "2026-11-19",
                       "facts": [FACT], "cost_usd": 0.1})
    assert case["public_facts"] == [FACT]
    assert apply_rules(case)["priority"] == "P3"
