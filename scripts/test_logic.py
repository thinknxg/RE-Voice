#!/usr/bin/env python3
"""Offline tests for re_voice's pure logic (no Frappe site required)."""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "re_voice"))

from intent.entities import (parse_budget_range, parse_bedrooms, parse_datetime,
                             parse_money, parse_name, parse_phone, parse_unit_type)
from intent.matcher import match

COMMANDS = [
    {"command_name": "Create Lead", "keywords": "create lead,new lead,add lead",
     "sample_phrases": "create a new lead named Rahul\nadd lead"},
    {"command_name": "Book Visit", "keywords": "book visit,schedule visit,site visit",
     "sample_phrases": "book a site visit tomorrow"},
    {"command_name": "Show Today's Follow-ups",
     "keywords": "today follow ups,follow ups today,my follow ups",
     "sample_phrases": "show me today's follow ups"},
    {"command_name": "Mark Lost", "keywords": "mark lost,lost deal",
     "sample_phrases": "mark this lead as lost"},
]


def test_money():
    assert parse_money("budget is forty five lakhs", "Indian") == 4500000.0
    assert parse_money("around 1.2 crore", "Indian") == 12000000.0
    assert parse_money("45 lakhs", "Indian") == 4500000.0
    assert parse_money("OMR 45 thousand") == 45000.0
    assert parse_money("50k") == 50000.0
    assert parse_money("about 950000") == 950000.0
    assert parse_money("no numbers here") is None
    # locale matters: 'lakh' must not multiply under the international system
    assert parse_money("45 lakhs") == 45.0
    assert parse_budget_range("between 40 and 60 lakhs", "Indian") == \
        (4000000.0, 6000000.0)


def test_unit_types():
    assert parse_unit_type("looking for 2 BHK") == "2BR"
    assert parse_unit_type("need a two bedroom flat") == "2BR"
    assert parse_unit_type("studio apartment") == "Studio"
    assert parse_unit_type("5 bhk") == "4BR+"
    assert parse_unit_type("office space") == "Office"
    assert parse_unit_type("just calling to say hi") is None
    assert parse_bedrooms("3 BHK") == 3
    assert parse_bedrooms("studio") == 0


def test_datetimes():
    now = datetime(2026, 7, 1, 9, 0)          # Wednesday
    assert parse_datetime("tomorrow 4pm", now) == datetime(2026, 7, 2, 16, 0)
    assert parse_datetime("day after tomorrow morning", now) == \
        datetime(2026, 7, 3, 10, 0)
    assert parse_datetime("saturday evening", now) == datetime(2026, 7, 4, 18, 0)
    assert parse_datetime("today at 5:30 pm", now) == datetime(2026, 7, 1, 17, 30)
    assert parse_datetime("no date mentioned", now) is None


def test_contacts():
    assert parse_phone("his number is +968 9123 4567") == "+96891234567"
    assert parse_phone("call him soon") is None
    assert parse_name("create lead named Rahul Menon budget 45 lakhs") == "Rahul Menon"
    assert parse_name("new lead called Priya, wants 2 BHK") == "Priya"
    assert parse_name("create a lead for Ahmed Al Balushi interested in villas") == \
        "Ahmed Al Balushi"
    assert parse_name("book a visit") is None


def test_matcher():
    assert match("create a new lead for Rahul Menon", COMMANDS)[0] == "Create Lead"
    assert match("book a site visit tomorrow at 4", COMMANDS)[0] == "Book Visit"
    assert match("show me today's follow ups", COMMANDS)[0] == \
        "Show Today's Follow-ups"
    assert match("mark lost", COMMANDS)[0] == "Mark Lost"
    # Unknown input must fall through to the LLM tier, not guess
    assert match("what is the weather like", COMMANDS)[0] is None
    assert match("", COMMANDS) == (None, 0.0)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"{len(tests)} test groups passed.")
