"""Copy for the lead inventory's record-based signals: one templated line each,
read only from the lead's payload, ~8 words, no em dash, no dollar sign, no
date, and never "hiring" or "raised" anywhere in the sequence. Offline."""

from __future__ import annotations

from datetime import date

import pytest

from system_b.copy.email import (
    MAGNET_SIGNALS,
    RECORD_SIGNALS,
    build_email_1,
    build_followup_email,
    magnet_phrase,
    need_for,
)
from system_b.copy.linkedin import build_dm_1, build_dm_1_evergreen
from system_b.gift.engine import _cfo_what_category
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead, Signal
from system_b.niches.base import pack_for

TODAY = date(2026, 10, 18)
DB = "construction_federal_award_davis_bacon"
NL = "construction_new_licensed_business"
UP = "construction_license_upgrade"
CR = "federal_cost_reimbursement_contract"
FG = "federal_first_time_grant"
NB = "new_business_formed"


def lead(signal_type: str, payload: dict | None = None, *, name: str = "Acme Builders Llc",
         city: str = "Tampa", state: str = "FL", lid: str | None = None) -> Lead:
    return Lead(
        id=lid or f"{signal_type}:{name}", company=name, city=city, state=state,
        industry="construction", signal_type=signal_type, entity_id=f"uei:{name}",
        signals=[Signal(type=signal_type, date="2026-10-06", date_confidence="high",
                        plain_words_description="Won a $498K federal award on 2026-10-06.",
                        source_url="https://www.usaspending.gov/award/X/",
                        payload=dict(payload or {}))],
    )


# (signal type, payload, the line it must render)
CASES = [
    (DB, {"first_contract_on_record": False, "awards_in_window": 1},
     "won a federal job, weekly certified payroll"),
    (DB, {"first_contract_on_record": False, "awards_in_window": 7},
     "won federal jobs, weekly certified payroll"),
    (DB, {"first_contract_on_record": True, "awards_in_window": 1},
     "first federal job on record, weekly certified payroll"),
    (DB, {"first_contract_on_record": True, "awards_in_window": 2},
     "first federal jobs on record, weekly certified payroll"),
    (NL, {"formed_class": "new_company"}, "new contracting company, just licensed"),
    (NL, {"formed_class": "existing_company"}, "newly licensed contractor"),
    (NL, {"formed_class": "unknown"}, "newly licensed contractor"),
    (NL, {"state": "WA", "license": "ALLSECC741PN"}, "newly licensed in washington"),
    (NL, {"formed_class": "new_company", "lookup": "https://www.myfloridalicense.com/x"},
     "new contracting company, just licensed"),
    (UP, {"license_class": "CGC", "prior_license": "CBC1254464"},
     "moved up to a general contractor license"),
    (UP, {"license_class": "CBC", "prior_license": "CRC1"},
     "moved up to a building contractor license"),
    (UP, {}, "moved up to a bigger contractor license"),
    (CR, {"pricing_kind": "cost-reimbursement"},
     "federal contract where every cost is auditable"),
    (CR, {"pricing_kind": "time-and-materials"}, "hourly federal contract, hours can be audited"),
    (CR, {"pricing_kind": "labor-hour"}, "hourly federal contract, hours can be audited"),
    (CR, {}, "federal contract the government can audit"),
    (FG, {"grants_in_window": 2}, "first federal grant in 3+ years"),
    (NB, {"state": "FL", "entity_kind": "LLC"}, "just registered as a new company"),
    (NB, {"state": "CT", "entity_kind": "LLC"}, "just registered as a new company in connecticut"),
]

# Printed state differs from the licensing state: say where it was licensed.
ELSEWHERE = [
    (NL, {"state": "WA", "lookup": "Search license X at https://secure.lni.wa.gov/verify/"},
     "OR", "newly licensed in washington"),
    (NL, {"state": "WA", "lookup": "https://secure.lni.wa.gov/verify/"}, "WA",
     "newly licensed contractor"),
    (NL, {"formed_class": "new_company", "lookup": "https://www.myfloridalicense.com/x"},
     "GA", "new contracting company, just licensed in florida"),
    (UP, {"license_class": "CGC", "lookup": "https://www.myfloridalicense.com/x"}, "AL",
     "moved up to a florida general contractor license"),
    (UP, {"license_class": "CRC"}, "FL", "moved up to a residential contractor license"),
    (NB, {"state": "CT"}, "CA", "just registered as a new company in connecticut"),
    (NB, {"state": "CO"}, "CO", "just registered as a new company"),
]


@pytest.mark.parametrize("signal_type,payload,state,want", ELSEWHERE)
def test_a_license_or_filing_from_another_state_says_which(signal_type, payload, state, want):
    said = magnet_phrase(lead(signal_type, payload, state=state))
    assert said == want and len(said.split()) <= 8


@pytest.mark.parametrize("signal_type,payload,want", CASES)
def test_each_record_signal_has_one_templated_line(signal_type, payload, want):
    said = magnet_phrase(lead(signal_type, payload))
    assert said == want
    assert len(said.split()) <= 8, said
    assert "—" not in said and "$" not in said
    words = set(said.replace(",", " ").split())
    assert not words & {"hiring", "raised", "ever"}, said
    # Audit is a right, never an event: "can be audited", not "get audited".
    assert "audited" not in words or "can be audited" in said, said


def test_every_record_signal_is_a_magnet_and_gets_a_line():
    assert RECORD_SIGNALS <= MAGNET_SIGNALS
    for t in RECORD_SIGNALS:
        assert magnet_phrase(lead(t))


def _gift(leads: list[Lead], geo: str = "city") -> Gift:
    return Gift(leads=leads, best_lead=leads[0], gift_size=len(leads), all_niche=False,
                geo_level=geo, subject_shape="singular" if len(leads) == 1 else "plural",
                what_category=_cfo_what_category(leads), best_lead_level=1)


PROSPECT = Prospect(firm_name="Ledger Books", city="Tampa", state="FL", first_name="Dana")


def _sequence_text(gift: Gift, pack_key: str) -> list[str]:
    pack = pack_for(pack_key)
    e1 = build_email_1(gift, PROSPECT, today=TODAY, pack=pack, include_signoff=False)
    e2 = build_followup_email(gift.leads[0], PROSPECT, step=2, today=TODAY, pack=pack,
                              gift_signals={ld.signal_type for ld in gift.leads})
    return [e1.subject, e1.body, e2.body, build_dm_1(gift, PROSPECT, pack=pack),
            build_dm_1_evergreen(gift, PROSPECT, pack=pack)]


@pytest.mark.parametrize("pack_key", ["cfo", "accounting", "bookkeeping"])
@pytest.mark.parametrize("signal_type", sorted(RECORD_SIGNALS))
def test_no_part_of_the_sequence_says_hiring_or_raised(pack_key, signal_type):
    one = _gift([lead(signal_type)])
    three = _gift([lead(signal_type, name=n) for n in ("A Llc", "B Llc", "C Llc")])
    for gift in (one, three):
        for text in _sequence_text(gift, pack_key):
            low = text.lower()
            assert "hiring" not in low and "raised" not in low, text
            assert "just posted" not in low and "—" not in text, text
            assert "$" not in text, text
            assert "ago" not in low, text            # magnet lines carry no relative date


def test_each_record_signal_gets_its_own_subject_category():
    cats = {t: _cfo_what_category([lead(t)]) for t in RECORD_SIGNALS}
    assert len(set(cats.values())) == len(RECORD_SIGNALS)
    assert not any(c in ("hiring", "raised", "mixed", "unstaffed") for c in cats.values())


def test_a_mixed_record_gift_says_only_that_records_show_a_need():
    mixed = [lead(DB), lead(NB, name="New Co Llc")]
    assert _cfo_what_category(mixed) == "public_record"
    assert need_for(_gift(mixed), default="looking for bookkeeping help right now") == \
        "showing they need finance help"
    subject = build_email_1(_gift(mixed), PROSPECT, today=TODAY,
                            pack=pack_for("bookkeeping")).subject
    assert "nobody" not in subject and "public records" in subject


def test_the_need_clause_names_the_record_event():
    assert need_for(_gift([lead(CR)]), default="X") == \
        "on federal contracts the government can audit"
    assert need_for(_gift([lead(NB)]), default="X") == "newly registered with the state"


def test_email_2_says_same_signal_only_when_it_is():
    pack = pack_for("cfo")
    other = lead(NB, name="New Co Llc")
    same = build_followup_email(lead(DB, name="B Llc"), PROSPECT, step=2, today=TODAY,
                                pack=pack, gift_signals={DB})
    diff = build_followup_email(other, PROSPECT, step=2, today=TODAY, pack=pack,
                                gift_signals={DB})
    assert "showing the same signal" in same.body
    assert "same signal" not in diff.body and "from public records" in diff.body
    assert "just registered as a new company" in diff.body
    assert "books" not in diff.body


def test_nonprofit_subjects_and_dms_say_what_the_audit_shows():
    """The old subject, "with no finance officer, from their 990s", was the
    removed Row 4 claim, and 3 of 24 charities under it listed an officer. A
    gift of audit findings says so; a mix (a late filing) stays neutral."""
    np = "nonprofit_grant_no_finance_officer"
    findings = [lead(np, {"fac_material_weakness": True}, name="A"),
                lead(np, {"fac_program_control_finding": True}, name="B")]
    mixed = [*findings, lead(np, {"fac_late": True, "fac_days_late": 90}, name="C")]
    assert _cfo_what_category(findings) == "nonprofit_audit"
    assert _cfo_what_category(mixed) == "public_record"
    for pack_key in ("cfo", "accounting", "bookkeeping"):
        subject, _e1, _e2, dm, evergreen = _sequence_text(_gift(findings), pack_key)
        assert "whose auditors flagged problems" in subject
        assert "whose auditors flagged problems" in evergreen
        for gift in (_gift(findings), _gift(mixed), _gift([mixed[-1]])):
            for text in _sequence_text(gift, pack_key):
                assert "finance officer" not in text and "990" not in text, text
        subject = _sequence_text(_gift(mixed), pack_key)[0]
        assert "public records" in subject, subject


NPS = "nonprofit_grant_no_finance_officer"


@pytest.mark.parametrize("payload,want", [
    ({"fac_program_control_finding": True}, "auditors flagged how they handle grants"),
    ({"fac_program_control_finding": True, "fac_program_repeat": True},
     "auditors flagged how they handle grants, two years running"),
    ({"fac_material_noncompliance": True}, "auditors flagged how they handle grants"),
    # A financial-statement finding still leads when both are there.
    ({"fac_material_weakness": True, "fac_program_control_finding": True},
     "auditors flagged their financial controls"),
])
def test_grant_compliance_findings_have_their_own_line(payload, want):
    said = magnet_phrase(lead(NPS, payload))
    assert said == want and len(said.split()) <= 9


def test_no_row_1_lead_falls_through_to_a_generic_line():
    """Row 1 emits only audit problems: a control finding, a program finding,
    or a late / missing audit. None may reach the 990-only fallbacks."""
    import itertools
    import json
    from pathlib import Path
    generic = ("files a federal audit", "no finance officer", "grant funded")
    problems = [{"fac_material_weakness": True}, {"fac_significant_deficiency": True},
                {"fac_program_control_finding": True}, {"fac_material_noncompliance": True},
                {"fac_overdue": True}, {"fac_late": True, "fac_days_late": 75}]
    for a, b in itertools.combinations_with_replacement(problems, 2):
        said = magnet_phrase(lead(NPS, {**a, **b, "no_finance_officer_listed": False}))
        assert not said.startswith(generic), said
    published = Path.home() / "Developer/Inventory/exports/magnets/nonprofit-leads.json"
    if published.exists():                       # the real Row 1 file, when on disk
        from system_b.clients.inventory import adapt_leadgen_lead
        for row in json.loads(published.read_text())["leads"]:
            said = magnet_phrase(adapt_leadgen_lead(row, today=TODAY))
            assert not said.startswith(generic), (row["name"], said)
