"""2026-11-21: fixes from reading 200 random emails of the 1,919 batch."""

from __future__ import annotations

from pathlib import Path

import pytest

from system_b.clients import inventory as inv
from system_b.copy.offer import followup_question
from system_b.gift.engine import _same_company
from system_b.models import Lead, Signal
from system_b.prospects import not_a_buyer_title, row_from_apollo, wrong_company_address

HAS_WORDS = Path("/usr/share/dict/words").exists()


def _lead(t, payload, name="Acme Widgets", state="CO", city="Denver"):
    return Lead(id=f"{t}:{name}", company=name, city=city, state=state, industry=None,
                signal_type=t, entity_id=f"x:{name}",
                signals=[Signal(type=t, date="2026-10-01", date_confidence="high",
                                plain_words_description="x", source_url="https://example.gov",
                                payload=payload)])


def _why(lead):
    pay = {}
    for s in lead.signals:
        pay.update(s.payload)
    return inv.review_reason({}, lead, pay)


# --- recipients ------------------------------------------------------------

def _apollo(**kw):
    rec = {"Website": "https://acmecpa.com", "Email": "jane@acmecpa.com", "First Name": "Jane",
           "Last Name": "Doe", "Company Name": "Acme CPA", "Title": "Owner"}
    rec.update(kw)
    return rec


def test_sales_broker_mentor_and_sold_firms_are_not_emailed():
    assert not_a_buyer_title("Vice President of Sales")
    assert not_a_buyer_title("Principle Broker and Founding Member")
    assert not_a_buyer_title("Mentor, Founder, Managing Member")
    assert not_a_buyer_title("Founder and CEO (Triple Leo Acquired by Sudrania Fund Services)")
    assert not not_a_buyer_title("Founder & CEO | Accounting and Business Growth Strategist")
    assert not not_a_buyer_title("Principal, Marketing and Fractional CFO")
    assert row_from_apollo(_apollo(Title="Vice President of Sales")) is None
    assert row_from_apollo(_apollo()) is not None


def test_an_address_at_another_organization_is_not_emailed():
    assert wrong_company_address("aconstantine@fb.com", "https://bookkeepingatoz.com",
                                 "A to Z Bookkeeping", "Anna", "Constantine")
    # A school district's address, though the firm carries her name.
    assert wrong_company_address("wendi.white@dcsdk12.org", "https://wendiconsultingllc.com",
                                 "Wendi Consulting", "Wendi", "White")
    assert not wrong_company_address("rod@mfgplanners.com", "https://mfgtaxservices.com",
                                     "MFG Tax Services", "Rod", "X")
    assert not wrong_company_address("teesbookkeeping@swva.net", "https://teestaxes.com",
                                     "Tee's Bookkeeping", "Tee", "X")
    assert row_from_apollo(_apollo(Email="qbonline@acmecpa.com")) is None
    assert row_from_apollo(_apollo(Website="https://fund.vc", Email="jane@fund.vc")) is None


# --- leads -----------------------------------------------------------------

def test_housing_properties_are_dropped():
    assert _why(_lead("nonprofit_single_audit_late", {"ntee_code": "L22"},
                      name="Rayne Elderly Housing Corporation")) == "housing_property"
    assert _why(_lead("nonprofit_single_audit_late", {},
                      name="Antonian Towers PA26-T841-007")) == "housing_property"
    # A HUD loan many times the charity's revenue.
    assert _why(_lead("nonprofit_questioned_costs",
                      {"total_revenue": 119715, "fac_federal_expended": 1292060},
                      name="Booth Ministries")) == "housing_property"
    # A nursing home ("Manor") with a real revenue is a business.
    assert _why(_lead("nonprofit_deficit_low_cash",
                      {"total_revenue": 8326060, "ntee_code": "E91"},
                      name="Magnolia Manor of Liberty County Inc")) is None


def test_tiny_nonprofits_are_dropped():
    assert _why(_lead("nonprofit_990_missed_1yr", {"total_revenue": 27260},
                      name="Hevelone Society")) == "too_small"


def test_cut_off_names_are_dropped_but_town_of_is_kept():
    assert _why(_lead("nonprofit_first_990", {}, name="Catholic Charities Of Central")) \
        == "cut_off_name"
    assert _why(_lead("construction_large_permit", {}, name="L&L Construction Develop")) \
        == "cut_off_name"
    assert _why(_lead("local_gov_single_audit_late", {}, name="Hot Springs, Town of")) is None
    assert _why(_lead("liquor_license_new_ca", {}, name="Beast of The East")) is None


def test_hospitals_are_too_big_but_animal_hospitals_are_not():
    assert _why(_lead("plan_late_contributions", {}, name="Holland Hospital")) == "too_big"
    assert _why(_lead("sba_7a_loan_approved", {},
                      name="Cape Fear Veterinary Emergency Hospital PLLC")) is None
    assert _why(_lead("sba_7a_loan_approved", {}, name="Total Care Medical Center LLC")) is None


def test_a_public_company_under_a_longer_name(monkeypatch):
    monkeypatch.setattr(inv, "_public_names", lambda: frozenset({"agilon health", "johnson and johnson"}))
    assert _why(_lead("plan_late_contributions", {}, name="Agilon Health Management, Inc.")) \
        == "public_company"
    assert _why(_lead("sam_new_entity_registration", {},
                      name="Johnson & Johnson Cleaning Service LLC")) is None


@pytest.mark.skipif(not HAS_WORDS, reason="needs the system word list")
def test_people_and_family_foundations_are_dropped(monkeypatch):
    monkeypatch.setattr(inv, "_first_names", lambda: frozenset({"nisha", "jill", "audrey", "rob",
                                                                 "katie", "vincent", "taylor"}))
    assert _why(_lead("plan_late_contributions", {}, name="Nisha Jackson")) == "person_name"
    assert _why(_lead("federal_cost_reimbursement_contract", {}, name="Jill A Oliver")) \
        == "person_name"
    assert _why(_lead("nonprofit_state_audit_line_no_audit", {"ntee_code": "P840"},
                      name="Vincent House Inc")) is None
    assert _why(_lead("nonprofit_first_990", {"total_revenue": 500000},
                      name="Rob And Katie Ruelas Family Foundation")) == "person_foundation"
    assert _why(_lead("nonprofit_state_audit_line_no_audit", {"total_revenue": 2270422},
                      name="Audrey Backus Charitable Trust")) == "person_foundation"
    # A memorial charity named for one person runs programs.
    assert _why(_lead("nonprofit_990_missed_1yr", {"total_revenue": 439466, "ntee_code": "F99"},
                      name="Taylor Hooton Foundation")) is None


def test_misspelled_names_are_swapped_not_corrected():
    for typo in ("Police Athlethic League of Wilmington Inc", "Utah Peer Support Specialests",
                 "Center for Independence of Individuals with Disabitilites Inc"):
        assert _why(_lead("nonprofit_going_concern", {"total_revenue": 500000}, name=typo)) \
            == "misspelled_name", typo
    for fine in ("Fundacion Corporacion Latina", "Communitas Inc", "Educational Alliance"):
        assert inv.misspelled_word(fine) is None, fine


def test_names_read_cleanly():
    c = inv._clean_company_name
    assert c("United Way Of West Tennessee") == "United Way of West Tennessee"
    assert c("Lavender Youth Recreation & Information Center LYRIC") \
        == "Lavender Youth Recreation & Information Center"
    assert c("Spatial Informatics Group Natural Assets Laboratory SIG-NAL") \
        == "Spatial Informatics Group Natural Assets Laboratory"
    assert c("Mckee Family Services") == "McKee Family Services"
    assert c("SU Casa Community Association") == "Su Casa Community Association"
    assert c("LA Casa DE Salud") == "La Casa de Salud"
    assert c("Down Syndrome Society Of Wichitainc") == "Down Syndrome Society of Wichita"
    assert c("St Peter's Church Housing Devel Development Fund Company") \
        == "St Peter's Church Housing Development Fund Company"
    assert c("Boat People SOS") == "Boat People SOS"


# --- one sequence, one operator --------------------------------------------

def test_sister_organizations_count_as_one():
    a = _lead("snf_change_of_ownership", {}, name="Adviniacare at Fairfield")
    b = _lead("snf_change_of_ownership", {}, name="Adviniacare of Bridgeport")
    assert _same_company(b, [a])
    c = _lead("plan_late_contributions", {"contact_name": "Mary Smith"}, name="Bear Mt Lodge")
    d = _lead("plan_late_contributions", {"contact_name": "Mary Smith"}, name="Bear Mt Inn")
    assert _same_company(d, [c])
    e = _lead("nonprofit_first_990", {}, name="Bakersfield Food Bank", city="Bakersfield")
    f = _lead("nonprofit_first_990", {}, name="Bakersfield Legal Aid", city="Bakersfield")
    assert not _same_company(f, [e])


# --- copy --------------------------------------------------------------------

def test_the_place_question_never_names_a_place_without_its_lead():
    assert followup_question(None, "fresno") == "should i keep these to fresno, or go wider?"
    assert followup_question(None, None).startswith("are these the kind of clients")


def test_a_state_that_is_part_of_the_name_stays():
    from system_b.copy.lex import spoken_name
    assert spoken_name("YWCA of Southern Arizona") == "YWCA of Southern Arizona"
    assert spoken_name("Land Trust for Louisiana") == "Land Trust for Louisiana"
    assert spoken_name("United Way of West Tennessee") == "United Way of West Tennessee"
    assert spoken_name("Grace House of Memphis Tennessee") == "Grace House of Memphis"


def test_registry_city_short_forms_are_spelled_out():
    from system_b.copy.lex import city_display
    assert city_display("Santa Rsa Bch") == "santa rosa beach"
    assert city_display("Ft. Lauderdale") == "fort lauderdale"
    assert city_display("St Paul") == "st paul"


def test_apostrophes_in_childrens_and_womens():
    assert inv._clean_company_name("Childrens Home Society") == "Children's Home Society"
    assert inv._clean_company_name("Womens Fund of East Tennessee") == "Women's Fund of East Tennessee"


# --- full read of the 1,885 batch (2026-11-21) -------------------------------

def test_the_award_named_is_the_one_award_not_the_total():
    from system_b.copy.facts import record_fact
    lead = _lead("federal_construction_award",
                 {"award_amount": 159000, "awards_in_window": 2, "total_in_window": 201000})
    assert record_fact(lead, with_contact=False) == "$159k"


def test_more_no_value_leads_are_dropped():
    assert _why(_lead("hud_new_owner", {}, name="Chancellor Renovation LP")) == "housing_property"
    assert _why(_lead("nonprofit_going_concern", {}, name="Wilshire House 122-EH476")) \
        == "housing_property"
    assert _why(_lead("plan_fraud_loss", {"amount": 13}, name="The Avalon Group")) == "trivial_amount"
    assert _why(_lead("ny_omig_final_audit", {"amount": None}, name="Rome Health")) == "no_amount"
    assert _why(_lead("nonprofit_going_concern", {"fac_federal_expended": 138_100_000},
                      name="Healthx Partners")) == "too_big"
    assert _why(_lead("local_gov_single_audit_late", {}, name="Pike County School District")) \
        == "government"
    assert _why(_lead("nonprofit_going_concern", {},
                      name="Mandela Partners Prev Mandela Marketplace")) == "garbled_name"
    assert _why(_lead("plan_late_contributions", {}, name="Plan B")) is None


@pytest.mark.skipif(not HAS_WORDS, reason="needs the system word list")
def test_bare_person_names_are_dropped():
    assert _why(_lead("federal_cost_reimbursement_contract", {}, name="Damon McCoy")) == "person_name"
    assert _why(_lead("federal_cost_reimbursement_contract", {}, name="Casa Latina")) is None


def test_record_people_read_cleanly():
    from system_b.copy.facts import _person
    lead = _lead("nonprofit_going_concern", {})
    lead.contact_name, lead.contact_title = "Leigh McKELVEY", "Executive Director"
    assert _person(lead)[0] == "Leigh McKelvey"
    lead.contact_name = "Christina JD"
    assert _person(lead) is None
