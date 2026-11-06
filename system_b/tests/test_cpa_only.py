"""CPA-only leads (audits; an auditor's report on a licensee's statements) go
to CPA firms only (2026-11-05, the user). Offline."""

from __future__ import annotations

from system_b.gift.engine import build_gift, cpa_only
from system_b.gift.models import Prospect
from system_b.research.rung import detect_cpa
from system_b.tests.test_gift import FakeScraper, mk


def _tagged(id_, t, tags):
    ld = mk(id_, t, city="Austin", state="TX")
    ld.service_tags = list(tags)
    return ld


def test_a_cpa_is_told_by_its_name_title_or_own_words():
    assert detect_cpa(None, firm_name="Moore CPA LLC")
    assert detect_cpa(None, title="Partner, CPA")
    assert detect_cpa({"u": "Jane Smith, CPA, leads our audit practice."})
    assert detect_cpa({"u": "We are a full-service CPA firm in Austin."})
    assert not detect_cpa({"u": "We keep your books ready for your CPA at tax time."},
                          firm_name="Bright Books LLC", title="Owner")
    assert not detect_cpa(None, firm_name="Iconix Accounting")


def test_audit_leads_are_cpa_only_by_tag_or_type():
    assert cpa_only(_tagged("a", "plan_audit_first_due", ["benefit_plan_audit"]))
    assert cpa_only(_tagged("b", "nonprofit_single_audit_late", ["bookkeeping", "grant_accounting"]))
    assert cpa_only(_tagged("c", "fl_new_money_transmitter", ["audit_assurance", "fintech_accounting"]))
    assert not cpa_only(_tagged("d", "construction_federal_award_davis_bacon", ["construction_accounting"]))
    assert not cpa_only(_tagged("e", "nonprofit_going_concern", ["fractional_cfo"]))


def test_a_bookkeeper_never_gets_an_audit_lead_and_a_cpa_does():
    leads = [_tagged(f"p{i}", "plan_audit_first_due", ["benefit_plan_audit"]) for i in range(3)]
    leads += [_tagged(f"d{i}", "construction_federal_award_davis_bacon", ["construction_accounting"])
              for i in range(3)]
    sc = FakeScraper(leads)
    books = build_gift(Prospect(firm_name="Bright Books", city="Austin", state="TX"), sc)
    assert books and all(ld.signal_type != "plan_audit_first_due" for ld in books.leads)
    audits_only = FakeScraper(leads[:3])
    assert build_gift(Prospect(firm_name="Bright Books", city="Austin", state="TX"), audits_only) is None
    cpa = build_gift(Prospect(firm_name="Moore CPA", city="Austin", state="TX", is_cpa=True),
                     audits_only)
    assert cpa and all(ld.signal_type == "plan_audit_first_due" for ld in cpa.leads)
