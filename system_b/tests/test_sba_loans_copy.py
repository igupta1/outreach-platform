"""SBALoans (2026-11-04): an APPROVAL, never "funded"; no lender, person, dollars or date."""

from __future__ import annotations

from datetime import date

from system_b.copy.duty import DUTIES, HELD_DUTIES
from system_b.copy.email import build_email_1
from system_b.gift.engine import HELD_TYPES, TYPE_ORDER, _cfo_what_category
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead, Signal
from system_b.niches.base import pack_for

TODAY = date(2026, 11, 4)
DANA = Prospect(firm_name="Ledger Books", city="Tampa", state="FL", first_name="Dana")
TYPES = ("sba_7a_loan_approved", "sba_504_loan_approved")


def lead(t: str, name: str) -> Lead:
    return Lead(id=f"{t}:{name}", company=name, city="Tampa", state="FL", industry=None,
                signal_type=t, entity_id=f"sba:{name}",
                signals=[Signal(type=t, date="2026-09-01", date_confidence="high",
                                plain_words_description="SBA loan of $1,799,900 approved",
                                source_url="https://data.sba.gov/dataset/7a-504-foia",
                                payload={"loan_amount": 1799900.0, "lender_name": "Big Bank",
                                         "approval_date": "2026-09-01"})])


def body(leads: list[Lead]) -> str:
    g = Gift(leads=leads, best_lead=leads[0], gift_size=len(leads), all_niche=False,
             geo_level="city", subject_shape="singular" if len(leads) == 1 else "plural",
             what_category=_cfo_what_category(leads), best_lead_level=1)
    return build_email_1(g, DANA, today=TODAY, pack=pack_for("cfo"), include_signoff=False).body


def test_both_types_are_live_and_ranked():
    for t in TYPES:
        assert t in DUTIES and t not in HELD_DUTIES and t not in HELD_TYPES and t in TYPE_ORDER
    assert TYPE_ORDER[TYPES[0]] < TYPE_ORDER[TYPES[1]] < TYPE_ORDER["new_practice_npi"]


def test_wording_says_approved_and_names_no_lender_person_dollar_or_date():
    for t, prog in zip(TYPES, ("7(a)", "504"), strict=True):
        names = ["Acme Dental Pllc", "Birch Roofing Llc", "Cedar Cafe Inc"]
        b = body([lead(t, n) for n in names])
        low = b.lower()
        # 2026-11-05: plain words, and no "will likely owe" guess. 2026-11-13,
        # the user: the need in the same sentence.
        assert "just got sba loans and will need clean books for their lender" in low
        assert "7(a)" not in low
        assert "likely" not in low
        # 2026-11-05: one fact per lead from the record, the loan's size
        # (copy.facts), formatted, never the raw figure.
        for bad in ("funded", "big bank", "1,799,900", "2026"):
            assert bad not in low, (bad, b)
        assert "($1.8m loan)" in low
        for n in ("Acme Dental", "Birch Roofing", "Cedar Cafe"):
            assert n in b
        one = body([lead(t, "Acme Dental Pllc")]).lower()
        assert "just got an sba loan and will need clean books for its lender" in one
        assert "likely" not in one


def _aged(t: str, name: str, recent: bool) -> Lead:
    ld = lead(t, name)
    ld.signals[0].payload["approved_recently"] = recent
    return ld


def test_just_only_when_every_loan_is_recent():
    # 2026-11-15, the user: "just got" overstated loans approved months earlier.
    t = TYPES[0]
    fresh = body([_aged(t, n, True) for n in ("Acme Dental Pllc", "Birch Roofing Llc")]).lower()
    assert "just got sba loans" in fresh
    mixed = body([_aged(t, "Acme Dental Pllc", True), _aged(t, "Birch Roofing Llc", False)]).lower()
    assert "just got" not in mixed
    assert "got sba loans in the past year and will need clean books for their lender" in mixed
    one = body([_aged(t, "Acme Dental Pllc", False)]).lower()
    assert "got an sba loan in the past year and will need clean books for its lender" in one
    d = DUTIES[t]
    assert d.short_for([_aged(t, "A", False), _aged(t, "B", True)]) == "with sba loans in the past year"
    assert d.short_for([_aged(t, "A", True)]) == "that just got an sba loan"
    for p in ("with sba loans in the past year", "with an sba loan in the past year"):
        assert len(p) <= 34


def test_loader_marks_recency():
    from system_b.clients.inventory import SBA_RECENT_DAYS, _mark_sba_recency
    t = TYPES[0]
    new, old = lead(t, "New Co"), lead(t, "Old Co")
    old.signals[0].date = "2026-01-02"
    _mark_sba_recency(new, TODAY)
    _mark_sba_recency(old, TODAY)
    assert SBA_RECENT_DAYS == 120
    assert new.signals[0].payload["approved_recently"] is True
    assert old.signals[0].payload["approved_recently"] is False
