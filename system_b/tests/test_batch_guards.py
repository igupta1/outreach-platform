"""The 2026-11-15 read of all 200 emails, as guards: cut-off names, the
capital, a job word as a first name, security grants. Each case is a real
line from that batch."""

from __future__ import annotations

import pytest

from system_b.clients.inventory import _clean_city, _complete_names, irs_cut_name
from system_b.copy.facts import contact
from system_b.copy.lex import city_state_display
from system_b.models import Lead
from system_b.review.checks import check_card


def _row(name, ein, kind="nonprofit_going_concern"):
    return {"name": name, "signal_type": kind, "signals": [{"payload": {"ein": ein}}]}


def test_a_cut_name_takes_the_same_eins_full_name():
    rows = [_row("National Association Of Clean", "123456789"),
            _row("National Association Of Clean Air Agencies", "12-3456789", "nonprofit_audit"),
            _row("National Association Of Clean", "999999999")]
    assert _complete_names(rows) == 1
    assert rows[0]["name"] == "National Association Of Clean Air Agencies"
    assert rows[2]["name"] == "National Association Of Clean"     # another EIN: never


def test_a_shorter_or_different_name_is_never_taken():
    rows = [_row("Hope House", "111111111"), _row("Hope Housing Partners", "111111111")]
    assert _complete_names(rows) == 0


@pytest.mark.parametrize("name", [
    "Public Health Institute of Metropolitan", "New York City Gay And Lesbian",
    "National Association Of Minority", "The International Centre For Missing",
    "Connecticut Council Of Family", "Catholic Housing Corporation of Northern",
    "North Central Community Action Agency Neighborhood Center Pro"])
def test_names_the_source_cut_off_are_caught(name):
    assert irs_cut_name(name)


@pytest.mark.parametrize("name", [
    "Public Health Institute of Metropolitan Chicago", "Department of Health",
    "Center for Independence of Individuals with Disabilities", "Bang on a Can",
    "Youth Pro"])
def test_whole_names_are_left_alone(name):
    assert irs_cut_name(name) is None


def test_the_capital_is_washington_dc():
    assert _clean_city("Washington", "DC") == "Washington, DC"
    assert _clean_city("Washington", "District of Columbia") == "Washington, DC"
    assert _clean_city("Washington", "PA") == "Washington"
    assert city_state_display("Washington, DC", "DC") == "washington, dc"


def test_a_job_word_is_never_a_first_name():
    lead = Lead(id="1", company="World A Cuts Barber Institute", signal_type="x",
                contact_name="Placement Love", contact_title="Director")
    assert contact(lead) == ""
    lead.contact_name = "Love Placement"
    assert contact(lead) == "director Love Placement"


def test_security_grants_never_reach_an_email():
    from system_b.gift.engine import giftable
    grant = Lead(id="1", company="Temple Beth", signal_type="nsgp_security_grant_subaward")
    assert not giftable(grant)


def _card(state, email_1, leads=()):
    return {"company": "F", "email": "a@f.com", "first_name": "Ann", "state": state,
            "email_1_head": email_1, "leads": [{"company": c} for c in leads]}


def test_the_review_page_flags_what_got_through():
    body = ("hey ann,\n\nnoticed you work with nonprofits.\n\nthese 3 in washington were warned:\n\n"
            "1. Public Health Institute of Metropolitan ($9.4m in revenue)\n"
            "2. World A Cuts Barber Institute (director Placement Love)\n"
            "3. Temple Beth got a federal security grant")
    whats = [i["what"] for i in check_card(_card("DC", body, [
        "Public Health Institute of Metropolitan", "World A Cuts Barber Institute"]))]
    assert any(w.startswith("name looks cut off") for w in whats)
    assert any("washington, dc" in w for w in whats)
    assert any(w.startswith("a job word as a first name") for w in whats)
    assert any(w.startswith("a security-grant lead") for w in whats)


def test_a_clean_card_has_no_guard_items():
    body = ("hey ann,\n\nnoticed you work with nonprofits.\n\nthese 3 in washington, dc were warned:\n\n"
            "1. Public Health Institute of Metropolitan Chicago ($9.4m in revenue, ceo Karen Reitan)")
    card = {**_card("DC", body, ["Public Health Institute of Metropolitan Chicago"]), "gift_size": 3}
    assert check_card(card) == []
