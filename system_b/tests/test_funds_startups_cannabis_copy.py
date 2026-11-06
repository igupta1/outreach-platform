"""Funds (re-added), Startups and Cannabis (2026-10-30), pinned in the
record-opener format and held to their records:

- Funds: "run private funds with no outside administrator on their latest
  form adv" (Schedule D 7.B.(1) Q26(a)); a count of funds, never dollars.
  `adv_annual_amendment_overdue` is worded but HELD.
- Startups: the raise claim is allowed for this source only (each lead links
  its own Form D); no dollar figure, no date, no "round"; "tech startups"
  only when every lead was incorporated within five years.
- Cannabis: the tax "why" only when every lead's license class collects the
  state cannabis tax; never "280E"; a name appears once per gift.
  Traceability citations and suspensions are HELD.
"""

from __future__ import annotations

import re

import pytest
from datetime import date

from system_b.copy.duty import DUTIES, HELD_DUTIES
from system_b.copy.email import RECORD_SIGNALS, build_email_1, build_followup_email
from system_b.copy.subject import short_subject
from system_b.gift.engine import HELD_TYPES, TYPE_ORDER, _cfo_what_category, _same_company
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead, Signal
from system_b.niches.base import pack_for

TODAY = date(2026, 10, 30)
DANA = Prospect(firm_name="Ledger Books", city="Austin", state="TX", first_name="Dana")


def lead(t: str, name: str, payload: dict | None = None, *, industry: str = "software_saas",
         city: str = "Austin", state: str = "TX", ident: str | None = None) -> Lead:
    return Lead(id=f"{t}:{name}", company=name, city=city, state=state,
                industry=industry, signal_type=t, entity_id=ident or f"cik:{name}",
                signals=[Signal(type=t, date="2026-10-15", date_confidence="high",
                                plain_words_description="$14,031,768 sold of a $20,000,000 offering",
                                source_url="https://www.sec.gov/Archives/edgar/data/1/x",
                                payload=dict(payload or {}))])


def gift(leads: list[Lead]) -> Gift:
    return Gift(leads=leads, best_lead=leads[0], gift_size=len(leads), all_niche=False,
                geo_level="city", subject_shape="singular" if len(leads) == 1 else "plural",
                what_category=_cfo_what_category(leads), best_lead_level=1)


def body(g: Gift, p: Prospect = DANA) -> str:
    return build_email_1(g, p, today=TODAY, pack=pack_for("cfo"), include_signoff=False).body


# --- Funds -----------------------------------------------------------------------

def test_funds_open_on_their_form_adv_with_a_count_never_dollars():
    leads = [lead("adv_no_fund_administrator", n, {"unadmin_funds": k, "crd": n},
                  industry="investment_management")
             for n, k in (("Rising Point Capital", 4), ("Lone Star Advisors", 3),
                          ("Acacia Partners", 5))]
    text = body(gift(leads))
    assert ("these 3 fund managers in austin run private funds with no outside "
            "administrator on their latest form adv, so each handles its fund "
            "accounting in house:") in text
    assert "Rising Point Capital (4 funds)" in text
    assert "$" not in text
    assert short_subject(gift(leads), DANA) == "3 austin fund managers with no fund administrator"
    two = build_followup_email(leads[0], DANA, step=2, today=TODAY,
                               pack=pack_for("cfo")).body
    assert "runs 4 private funds with no outside administrator on its latest form adv" in two


def test_the_form_adv_amendment_type_is_worded_but_held():
    t = "adv_annual_amendment_overdue"
    assert t in HELD_DUTIES and t in HELD_TYPES and t in TYPE_ORDER
    assert t not in DUTIES and t not in RECORD_SIGNALS
    words = HELD_DUTIES[t].generic_plural()
    assert "not on file" not in words or "late" not in words
    assert "late" not in words and "delinquent" not in words


# --- Startups --------------------------------------------------------------------

@pytest.mark.skip(reason="Form D held 2026-11-05 (the user: 'a very commoditized signal')")
def test_startups_raise_opener_names_no_dollars_and_says_startups_only_when_all_young():
    young = [lead("startup_first_form_d", n, {"incorporated_within_five_years": True,
                                               "total_amount_sold": 14031768})
             for n in ("Bevel, Inc.", "Payloop, Inc.", "Sky Analytica Corp")]
    text = body(gift(young))
    assert ("these 3 tech startups in austin filed their first form d with the sec, "
            "so each has a new raise to get on its books:") in text
    assert "$" not in text and not re.search(r"\b20\d\d\b", text.split(":")[0])
    assert "round" not in text and "first funding" not in text
    mixed = young[:2] + [lead("startup_first_form_d", "Old Co Inc.",
                              {"incorporated_within_five_years": False})]
    assert "these 3 tech companies in austin filed their first form d" in body(gift(mixed))
    new = [lead("startup_new_form_d", n, {"incorporated_within_five_years": True})
           for n in ("Clasp, Inc.", "Valoros, Inc.", "UrgentIQ Inc.")]
    assert ("these 3 tech startups in austin filed new form ds with the sec for new "
            "private offerings, so each has a new raise to get on its books:") in body(gift(new))


def test_startup_types_are_held_and_rank_after_every_duty():
    # Held 2026-11-05 by the user ("a very commoditized signal"): wording kept.
    for t in ("startup_first_form_d", "startup_new_form_d"):
        assert t in HELD_DUTIES and t not in DUTIES and t in HELD_TYPES
        assert t not in RECORD_SIGNALS
    assert TYPE_ORDER["startup_first_form_d"] < TYPE_ORDER["startup_new_form_d"] \
        < TYPE_ORDER["new_business_formed"]


# --- Cannabis --------------------------------------------------------------------

def _can(t: str, name: str, payload: dict, ident: str) -> Lead:
    return lead(t, name, payload, industry="cannabis", city="Seattle", state="WA",
                ident=ident)


def test_cannabis_tax_why_only_when_every_license_collects_the_tax():
    shops = [_can("cannabis_new_license", n, {"license_kind": "retail",
                                              "collects_state_cannabis_tax": True}, f"s:{n}")
             for n in ("The Premium Bud LLC", "Total Cannabis, Inc", "Loud House INC")]
    p = Prospect(firm_name="Ledger Books", city="Seattle", state="WA", first_name="Dana")
    text = body(gift(shops), p)
    assert ("these 3 cannabis businesses in seattle got new state cannabis licenses, "
            "so each now has state cannabis tax returns to file:") in text
    assert "The Premium Bud (dispensary)" in text
    mixed = shops[:2] + [_can("cannabis_new_license", "Post Mountain Cannabis LLC",
                              {"license_kind": "cultivation",
                               "collects_state_cannabis_tax": False}, "s:pm")]
    text = body(gift(mixed), p)
    assert "got new state cannabis licenses:" in text and "tax returns" not in text
    assert "(cultivator)" in text


def test_cannabis_never_says_280e_and_holds_two_types():
    for t, d in {**DUTIES, **HELD_DUTIES}.items():
        if t.startswith("cannabis_"):
            assert "280" not in " ".join((d.generic_plural(), d.generic_singular(),
                                          d.phrase(lead(t, "x")), d.dm))
    for t in ("cannabis_traceability_violation", "cannabis_license_suspended"):
        assert t in HELD_TYPES and t not in RECORD_SIGNALS
    for t in ("cannabis_new_license", "cannabis_began_operations",
              "cannabis_tax_report_violation", "cannabis_licensee_tax_delinquent",
              "cannabis_recordkeeping_violation"):
        assert t in DUTIES and t not in HELD_TYPES


def test_a_wa_trade_name_on_two_ubis_is_listed_once():
    """WA LCB prints trade names: two KALEAFA stores are two businesses (two
    UBIs) but the reader would see one name twice."""
    a = _can("cannabis_tax_report_violation", "KALEAFA", {}, "state_id:WA:UBI:603322058")
    b = _can("cannabis_tax_report_violation", "KALEAFA", {}, "state_id:WA:UBI:603586169")
    assert _same_company(b, [a])


def test_a_trade_name_with_a_tail_is_listed_once_too():
    a = _can("cannabis_tax_report_violation", "Have A Heart", {}, "state_id:WA:UBI:1")
    b = _can("cannabis_tax_report_violation", "Have A Heart CC", {}, "state_id:WA:UBI:2")
    assert _same_company(b, [a]) and _same_company(a, [b])
    c = _can("cannabis_new_license", "Acme", {}, "x:1")
    d = _can("cannabis_new_license", "Acme Roofing", {}, "x:2")
    assert not _same_company(d, [c])


def test_every_published_fund_lead_renders_a_clean_line():
    import json

    from system_b.clients.inventory import adapt_leadgen_lead
    from system_b.copy.email import _record_detail, _record_predicate, magnet_phrase
    from system_b.morning import INVENTORY_DIR
    path = INVENTORY_DIR / "fund-leads.json"
    if not path.exists():
        import pytest
        pytest.skip("fund-leads.json not published on disk")
    rows = json.loads(path.read_text()).get("leads") or []
    for row in rows:
        assert row["signal_type"] == "adv_no_fund_administrator"
        assert row["industry"] == "investment_management" and row["niche"] == "private_funds"
        ld = adapt_leadgen_lead(row, today=TODAY)
        assert ld.entity_id and ld.entity_id.split(":")[0] in ("crd", "cik")
        for text in (magnet_phrase(ld), _record_predicate(ld) or "",
                     _record_detail(ld, "adv_no_fund_administrator")):
            assert "—" not in text and "$" not in text and "None" not in text, text
        assert _record_predicate(ld).endswith("on its latest form adv")
