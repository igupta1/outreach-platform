"""The legal-duty record signals (2026-10-27, `copy.duty`): every approved type
renders in the record-opener format with no fallback line, no em dash, no
"None", no figure, and no line longer than the original six allow; a few
representative renders are pinned exactly. Offline (the last test reads the
published files when they are on disk)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from system_b.clients.inventory import MAGNETS, _taxonomy_tags, adapt_leadgen_lead
from system_b.copy.duty import DUTIES
from system_b.copy.email import (
    _RECORD_WHY,
    RECORD_SIGNALS,
    _grounded_line,
    _record_predicate,
    build_email_1,
    build_followup_email,
    magnet_phrase,
    record_opener,
)
from system_b.copy.linkedin import build_connect_note, build_dm_1_evergreen
from system_b.copy.subject import RECORD_PLURAL_WHAT, RECORD_SINGULAR_WHAT, short_subject
from system_b.gift.engine import (
    _MAGNET_WHAT,
    TYPE_ORDER,
    _audited_by,
    _cfo_what_category,
    _off_limits,
)
from system_b.gift.engine import RECORD_SIGNALS as ENGINE_RECORD
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead, Signal
from system_b.niches.base import pack_for

TODAY = date(2026, 10, 27)
ORIGINAL = {"construction_federal_award_davis_bacon", "construction_new_licensed_business",
            "construction_license_upgrade", "federal_cost_reimbursement_contract",
            "federal_first_time_grant", "new_business_formed"}
# The longest predicate + why the original record kinds say (the audit one).
LONGEST = max(len(p[0]) + 2 + len(w[0]) for p, w in _RECORD_WHY.values())


def lead(signal_type: str, payload: dict | None = None, *, name: str = "Acme Holdings Llc",
         city: str = "Columbus", state: str = "OH", industry: str | None = None,
         niche: str | None = None) -> Lead:
    return Lead(
        id=f"{signal_type}:{name}", company=name, city=city, state=state, industry=industry,
        niche=niche, signal_type=signal_type, entity_id=f"ein:{name}",
        signals=[Signal(type=signal_type, date="2026-09-01", date_confidence="high",
                        plain_words_description="Reported $125,455 of late contributions.",
                        source_url="https://example.gov/record",
                        payload=dict(payload or {}))],
    )


def gift(leads: list[Lead], geo: str = "city") -> Gift:
    return Gift(leads=leads, best_lead=leads[0], gift_size=len(leads), all_niche=False,
                geo_level=geo, subject_shape="singular" if len(leads) == 1 else "plural",
                what_category=_cfo_what_category(leads), best_lead_level=1)


DANA = Prospect(firm_name="Ledger Books", city="Columbus", state="OH", first_name="Dana")


def body(g: Gift, p: Prospect = DANA, pack: str = "cfo") -> str:
    return build_email_1(g, p, today=TODAY, pack=pack_for(pack), include_signoff=False).body


# --- the vocabulary is one list ------------------------------------------------------

def test_every_duty_type_is_a_record_signal_in_copy_and_engine():
    assert set(DUTIES) == RECORD_SIGNALS - ORIGINAL
    assert RECORD_SIGNALS == ENGINE_RECORD
    assert len(DUTIES) == 63
    for t in DUTIES:
        assert t in TYPE_ORDER, t
        assert _MAGNET_WHAT[t] == t
        assert RECORD_PLURAL_WHAT[t] and RECORD_SINGULAR_WHAT[t]


def test_the_inventorys_approved_list_is_this_list():
    """Inventory sources.APPROVED_SIGNALS is what publish lets through; a type
    with no wording here would print the raw evidence."""
    inv = Path.home() / "Developer/Inventory/leadinv/sources.py"
    if not inv.exists():
        pytest.skip("no inventory checkout")
    import ast
    tree = ast.parse(inv.read_text())
    approved = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                    if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", "") == "APPROVED_SIGNALS" for t in n.targets))
    assert set(approved) == set(DUTIES)


def test_strong_duties_rank_ahead_of_weak_ones_and_row_8_stays_last():
    order = TYPE_ORDER.__getitem__
    assert order("nonprofit_grant_no_finance_officer") == 0
    # An auditor's or regulator's finding before a first-time duty, before a
    # reported tax debt, before the original grant / license rows.
    assert order("nonprofit_questioned_costs") < order("construction_federal_award_davis_bacon")
    assert order("federal_cost_reimbursement_contract") < order("plan_audit_first_due")
    assert order("plan_audit_first_due") < order("late_filing_notice")
    assert order("late_filing_notice") < order("state_tax_lien")
    assert order("plan_late_contributions") < order("federal_first_time_grant")
    assert order("federal_first_time_grant") < order("construction_license_upgrade") \
        < order("construction_new_licensed_business")
    assert max(TYPE_ORDER.values()) == order("new_business_expanding")
    assert order("new_business_formed") > max(order(t) for t in DUTIES)
    assert len(set(TYPE_ORDER.values())) == len(TYPE_ORDER)     # one kind fills a gift


# --- every type renders cleanly ------------------------------------------------------

def _texts(t: str) -> list[str]:
    one = gift([lead(t)])
    three = gift([lead(t, name=n) for n in ("Alpha Llc", "Beta Inc", "Gamma Co")])
    pack = pack_for("cfo")
    out = []
    for g in (one, three):
        e1 = build_email_1(g, DANA, today=TODAY, pack=pack, include_signoff=False)
        out += [e1.subject, e1.body, build_dm_1_evergreen(g, DANA, pack=pack),
                build_connect_note(g, DANA, pack=pack) or ""]
    e2 = build_followup_email(three.leads[0], DANA, step=2, today=TODAY, pack=pack,
                              gift_signals={t})
    return [*out, e2.body]


@pytest.mark.parametrize("t", sorted(DUTIES))
def test_every_duty_type_renders_with_no_fallback_and_no_leak(t):
    d = DUTIES[t]
    ld = lead(t)
    said = magnet_phrase(ld)
    assert said and said != _grounded_line(ld).lower()
    assert len(said.split()) <= 8 and len(said) <= 54, said
    assert _record_predicate(ld)
    pred, why = d.generic_plural(), d.why_for([ld, ld])
    assert len(pred) + (2 + len(why) if why else 0) <= LONGEST, (pred, why)
    for n in (1, 3):
        assert len(d.short_for([], n)) <= 34
    for text in _texts(t):
        low = text.lower()
        assert "—" not in text and "$" not in text and "None" not in text, text
        assert "hiring" not in low and "raised" not in low and " ago" not in low, text
        assert "125,455" not in text and "late contributions." not in text   # never the evidence
    assert record_opener(gift([ld]), DANA) is not None


@pytest.mark.parametrize("t", sorted(DUTIES))
def test_a_mixed_gift_keeps_each_duty_line(t):
    other = lead("federal_first_time_grant", name="Grant Co")
    framing, lines = record_opener(gift([lead(t), other]), DANA)
    assert framing.endswith("that need finance help:")
    assert lines[0] == f"Acme Holdings: {magnet_phrase(lead(t))}"


# --- representative renders, exactly -------------------------------------------------

def test_a_first_plan_audit_gift_renders_exactly():
    g = gift([lead("plan_audit_first_due", name=n) for n in
              ("Car Source Llc", "Bright Dental Group", "Summit Roofing Inc")])
    assert body(g) == (
        "hey dana,\n\n"
        "saw you're based in columbus. these 3 companies in columbus have retirement plans "
        "past 120 account holders on their latest form 5500, so each needs its first "
        "plan audit:\n\n"
        "1. Car Source\n2. Bright Dental Group\n3. Summit Roofing\n\n"
        "i'm an engineer. i built a system that finds companies showing signs they need "
        "finance help.\n\n"
        "worth a look? happy to set it up for you either way :)")
    assert short_subject(g, DANA) == "3 columbus companies needing their first plan audit"


def test_new_york_tax_warrants_say_warrants_and_no_amount():
    ny = Prospect(firm_name="X", city="Syracuse", state="NY", first_name="Al")
    w = {"jurisdiction": "NY", "instrument": "NYS tax warrant", "amount": 6158407.77}
    g = gift([lead("state_tax_lien", w, name=n, city="Syracuse", state="NY")
              for n in ("Blacktop Sealcoat Llc", "Audax Enterprise Inc")])
    framing, lines = record_opener(g, ny)
    assert framing == ("saw you're based in syracuse. these 2 companies in syracuse had "
                       "state tax warrants filed against them:")
    assert lines == ["Blacktop Sealcoat", "Audax Enterprise"]
    assert short_subject(g, ny) == "2 syracuse companies with state tax warrants"
    lien = lead("state_tax_lien", {"instrument": "Connecticut Department of Revenue "
                                                 "Services tax lien"}, name="C Llc")
    assert magnet_phrase(lien) == "state tax lien filed against them"


def test_a_new_medicare_provider_names_its_kind():
    tx = Prospect(firm_name="X", city="Beaumont", state="TX", first_name="Jo")
    kinds = ("PART A PROVIDER - HOSPICE", "PART A PROVIDER - HOME HEALTH AGENCY")
    g = gift([lead("medicare_new_part_a_provider", {"provider_type_text": k}, name=n,
                   city="Beaumont", state="TX", industry="healthcare")
              for k, n in zip(kinds, ("Help Hospice Llc", "Rhema Home Health Inc"))])
    framing, lines = record_opener(g, tx)
    assert framing == ("saw you're based in beaumont. these 2 providers in beaumont newly "
                       "enrolled in medicare, so each owes its first medicare cost report:")
    assert lines == ["Help Hospice (hospice)", "Rhema Home Health (home health agency)"]
    e2 = build_followup_email(g.leads[0], tx, step=2, today=TODAY, pack=pack_for("cfo"))
    assert e2.body.startswith("one more in beaumont: Help Hospice newly enrolled in "
                              "medicare as a hospice.")


def test_a_late_union_report_says_how_late_and_calls_them_unions():
    g = gift([lead("union_lm_report_late", {"days_past_due": d}, name=n)
              for d, n in ((560, "Teamsters, LU 683"), (95, "Boilermakers, LG 92"))])
    framing, lines = record_opener(g, DANA)
    assert framing.endswith("these 2 unions in columbus filed their yearly labor "
                            "department financial reports late:")
    assert lines == ["Teamsters, LU 683 (18 months late)", "Boilermakers, LG 92 (3 months late)"]
    assert "organizations showing signs" in body(g)          # the engineer line


def test_a_mixed_line_speaks_like_row_1():
    """In a mixed charity gift a duty line sits beside Row 1's "auditors flagged
    their financial controls", so it says "their" too, and how late."""
    late = lead("nonprofit_single_audit_late", {"fac_days_late": 205}, industry="nonprofit")
    assert magnet_phrase(late) == "filed their federal audit 6 months late"
    assert magnet_phrase(lead("nonprofit_going_concern")) == \
        "going-concern warning in their federal audit"


def test_a_medicaid_audit_says_money_is_owed_only_when_every_report_does():
    owed = [lead("ny_omig_final_audit", {"amount": 1139.46}, name=n, industry="healthcare")
            for n in ("Promesa", "Pioneer Homecare Inc")]
    assert record_opener(gift(owed), DANA)[0].endswith(
        "got final medicaid audit reports from the state, and each report says money is "
        "owed back:")
    unread = [owed[0], lead("ny_omig_final_audit", {}, name="TCPRNC", industry="healthcare")]
    assert record_opener(gift(unread), DANA)[0].endswith(
        "got final medicaid audit reports from the state:")


def test_a_late_filing_notice_says_which_report_and_whether_it_landed():
    notes = [lead("late_filing_notice", {"form": "NT 10-K"}, name="T-Rex Acquisition Corp"),
             lead("late_filing_notice", {"form": "NT 10-Q", "late_report_filed_on":
                                         "2026-09-02"}, name="Kinetic Group Inc")]
    assert record_opener(gift(notes), DANA)[1] == [
        "T-Rex Acquisition (10-k, not on edgar yet)", "Kinetic Group (10-q)"]


def test_a_film_credit_with_no_city_prints_no_state_three_times():
    ca = Prospect(firm_name="X", city="Burbank", state="CA", first_name="Lu")
    g = gift([lead("film_ca_credit_allocated", name=n, city=None, state="CA")
              for n in ("Glue The Film, Llc", "Farewell To Thieves, Llc")], geo="state")
    framing, lines = record_opener(g, ca)
    assert framing == ("saw you're based in burbank. these 2 production companies in "
                       "california were allocated state film tax credits, so each needs a "
                       "cpa report to get its credit certificate:")
    assert lines == ["Glue The Film", "Farewell To Thieves"]


# --- the data path ----------------------------------------------------------------------

def test_duty_sources_are_tagged_in_the_taxonomys_words():
    assert _taxonomy_tags("healthcare", "hospice") == ("healthcare", "senior_care")
    assert _taxonomy_tags("other", "higher_education") == ("education", "higher_ed")
    assert _taxonomy_tags("finance_real_estate", "broker_dealer") == (None, None)
    assert _taxonomy_tags("food_beverage", "winery") == ("ecommerce_retail", "cpg_food_beverage")
    assert _taxonomy_tags("other", "labor_union") == (None, None)
    # The original five already emit taxonomy words: passed through.
    assert _taxonomy_tags("construction", "specialty_trades") == ("construction",
                                                                  "specialty_trades")


@pytest.mark.parametrize("key,value,want", [
    ("npi", "1205263423", "npi:1205263423"),
    ("cik", "1437750", "cik:1437750"),
    ("ncua_charter", "8585", "ncua_charter:8585"),
    ("olms_file_number", "27119", "olms_file_number:27119"),
    ("hud_owner_participant_id", "445538", "hud_owner:445538"),
    ("warrant_ids", ["E-0961-W018-9", "E-0961-W019-1"], "ny_warrant:E-0961-W018-9"),
])
def test_the_new_id_kinds_make_a_duty_lead_findable(key, value, want):
    row = {"id": "x", "name": "Acme", "signal_type": "auditor_change", "city": "Irvine",
           "state": "CA", "status": "active", "expires_at": "2026-12-26",
           "signals": [{"type": "auditor_change", "event_date": "2026-10-16",
                        "payload": {key: value}}]}
    got = adapt_leadgen_lead(row, today=TODAY)
    assert got.entity_id == want and got.is_findable
    row["signals"][0]["payload"] = {"warrant_ids": []}
    assert adapt_leadgen_lead(row, today=TODAY).entity_id is None


def test_a_state_program_record_never_reaches_a_firm_in_another_state():
    """A Saint Paul contractor's first Washington prevailing-wage filing is true
    and beside the point for a Minnesota firm, like another state's license."""
    wa = lead("construction_first_prevailing_wage_intent", {"state": "WA"},
              city="Saint Paul", state="MN")
    assert _off_limits(wa, Prospect(firm_name="X", city="Saint Paul", state="MN"))
    assert not _off_limits(wa, Prospect(firm_name="X", city="Seattle", state="WA"))


def test_a_plan_auditor_never_gets_its_own_client():
    ld = lead("plan_audit_first_filed", {"auditor_firm": "CST GROUP CPAS PC"})
    assert _audited_by(ld, Prospect(firm_name="CST Group CPAs"))
    assert not _audited_by(ld, Prospect(firm_name="Ledger Books"))


def test_every_published_duty_lead_renders_a_clean_line():
    """Ground truth when the inventory's files are on disk: every approved lead
    (up to 400 a type) gets its own line, email 2 sentence and detail, none
    empty, none with an em dash, a figure or 'None'."""
    from system_b.morning import INVENTORY_DIR

    seen: dict[str, int] = {}
    for key, name in MAGNETS.items():
        path = INVENTORY_DIR / name
        if key in ("nonprofit", "construction", "govcon", "grant", "newbusiness") \
                or not path.exists():
            continue
        for row in json.loads(path.read_text()).get("leads") or []:
            t = row["signal_type"]
            assert t in DUTIES, f"{name} publishes {t}, which has no wording"
            if seen.get(t, 0) >= 400:
                continue
            seen[t] = seen.get(t, 0) + 1
            ld = adapt_leadgen_lead(row, today=TODAY)
            for text in (magnet_phrase(ld), _record_predicate(ld) or "",
                         DUTIES[t].detail_for(ld)):
                assert "—" not in text and "$" not in text and "None" not in text, (t, text)
            assert magnet_phrase(ld) and _record_predicate(ld)
    if not seen:
        pytest.skip("no duty magnet published on disk")


@pytest.mark.parametrize("name,person", [
    ("S Sato", True), ("Tracey A. Keahi CPA", True), ("Rene S. Mediavillo, MD", True),
    ("Reeves, Richard Gordon", True), ("Jack M. Bailey, JR.", True),
    ("Roth & Company", False), ("Juniper Networks", False), ("Chickasaw Nation", False),
    ("Cedar County, Missouri", False), ("A Place For Kids", False), ("Visa", False),
    ("Ezell Askew Jr MD Inc", True), ("S Sato LLC", True), ("Teamsters, LU 683", False),
    ("Stop N Go Inc", False), ("Dexter, Town of", False),
])
def test_a_persons_name_is_never_a_duty_lead(name, person):
    from system_b.clients.inventory import _unusable_reason
    from system_b.clients.people import looks_like_person
    assert looks_like_person(name) is person
    ld = lead("plan_late_contributions", name=name)
    assert (_unusable_reason({}, ld) == "person_name") is person
    # A Form 5500 sponsor named plainly is a person; elsewhere two plain words
    # are a normal organization name.
    from system_b.clients.inventory import _unusable_reason as why
    assert why({"name": "KREYNE SATO"}, lead("plan_late_contributions", name="Kreyne Sato")) \
        == "person_name"
    assert why({}, lead("union_funds_shortage", name="Kreyne Sato")) is None
    # The original five are judged as before: no person rule there.
    assert _unusable_reason({}, lead("federal_first_time_grant", name=name)) is None
