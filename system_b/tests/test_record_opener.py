"""The record opener (2026-10-24): when every lead in an email shares one kind
of record, the opener states it once with why it matters in the same sentence,
and the lines carry only what differs. Offline."""

from __future__ import annotations

from datetime import date

from system_b.copy.email import build_email_1, record_opener
from system_b.gift.engine import _cfo_what_category
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead, Signal
from system_b.niches.base import pack_for

TODAY = date(2026, 10, 24)
NP = "nonprofit_grant_no_finance_officer"
DB = "construction_federal_award_davis_bacon"
CR = "federal_cost_reimbursement_contract"
FG = "federal_first_time_grant"
NL = "construction_new_licensed_business"
NB = "new_business_formed"


def lead(signal_type: str, payload: dict | None = None, *, name: str = "Acme",
         city: str = "Atlanta", state: str = "GA", industry: str = "nonprofit") -> Lead:
    return Lead(
        id=f"{signal_type}:{name}", company=name, city=city, state=state,
        industry=industry, signal_type=signal_type, entity_id=f"ein:{name}",
        signals=[Signal(type=signal_type, date="2026-10-06", date_confidence="high",
                        plain_words_description="x", source_url="https://example.org/x",
                        payload=dict(payload or {}))],
    )


def gift(leads: list[Lead], *, all_niche: bool = False, geo: str = "city") -> Gift:
    return Gift(leads=leads, best_lead=leads[0], gift_size=len(leads), all_niche=all_niche,
                geo_level=geo, subject_shape="singular" if len(leads) == 1 else "plural",
                what_category=_cfo_what_category(leads), best_lead_level=1)


# Audits accepted within a year of the record's as-of date: "now has to".
NEW = {"fac_accepted_date": "2026-03-02", "fac_as_of": "2026-10-24"}
OLD = {"fac_accepted_date": "2025-02-14", "fac_as_of": "2026-10-24"}
MW = {"fac_material_weakness": True, **NEW}
REPEAT = {"fac_material_weakness": True, "fac_repeat_material_weakness": True, **NEW}
GRANTS = {"fac_program_control_finding": True, **NEW}

TROY = Prospect(firm_name="Peach Cfo", city="Atlanta", state="GA", first_name="Troy",
                classification="niched", match_param=("industry", "nonprofit"),
                niche_source="site", client_revenue=(3_000_000, None))


def test_the_users_example_renders_exactly():
    g = gift([lead(NP, REPEAT, name="Georgia Court Appointed Special Advocates"),
              lead(NP, MW, name="Cathedral Towers"),
              lead(NP, REPEAT, name="Georgia Works")], all_niche=True)
    body = build_email_1(g, TROY, today=TODAY, pack=pack_for("cfo"),
                         include_signoff=False).body
    assert body == (
        "hey troy,\n\n"
        "saw you work with $3m+ nonprofits. these 3 in atlanta had weak financial "
        "controls flagged in their federal audits, so each now has to file a plan "
        "to fix it:\n\n"
        "1. Georgia Court Appointed Special Advocates (two years in a row)\n"
        "2. Cathedral Towers\n"
        "3. Georgia Works (two years in a row)\n\n"
        "i'm an engineer. i built a system that finds organizations like these, "
        "for fractional cfos.\n\n"
        "worth a look? happy to set it up for you either way :)"
    )


def test_mixed_audit_findings_say_problems_and_name_each():
    g = gift([lead(NP, MW, name="A"), lead(NP, GRANTS, name="B")], all_niche=True)
    framing, lines = record_opener(g, TROY)
    assert framing.endswith("these 2 in atlanta had problems flagged in their federal "
                            "audits, so each now has to file a plan to fix it:")
    assert lines == ["A (financial controls)", "B (grant handling)"]


def test_place_is_named_only_when_every_lead_is_there():
    g = gift([lead(DB, {}, name="A", city="Nashville", state="TN", industry="construction"),
              lead(DB, {"first_contract_on_record": True}, name="B", city="Memphis",
                   state="TN", industry="construction")], geo="state")
    p = Prospect(firm_name="X", city="Knoxville", state="TN", first_name="Jo")
    framing, lines = record_opener(g, p)
    assert framing == ("saw you're based in knoxville. these 2 companies in tennessee "
                       "won federal construction jobs, so each now owes weekly certified "
                       "payroll for every worker:")
    assert lines == ["A, nashville", "B, memphis (first on record)"]
    # Arlington WA is not Arlington TX: same city name, two states -> no place.
    g2 = gift([lead(FG, name="A", city="Arlington", state="WA"),
               lead(FG, name="B", city="Arlington", state="TX")], geo="none")
    framing2, lines2 = record_opener(g2, Prospect(firm_name="X", first_name="Jo"))
    assert framing2 == ("these 2 nonprofits got their first federal grant in 3+ years, "
                        "so each now has strict tracking and reporting rules to follow:")
    assert lines2 == ["A, arlington", "B, arlington"]


def test_licenses_and_registrations_get_no_why():
    for t, clause in ((NL, "with a new contractor license"),
                      (NB, "that just registered as new companies")):
        g = gift([lead(t, name="A", industry="construction"),
                  lead(t, name="B", industry="construction")])
        framing, _ = record_opener(g, Prospect(firm_name="X", first_name="Jo"))
        assert framing == f"here are 2 companies in atlanta {clause}:"
        assert " so " not in framing


def test_a_mix_of_kinds_keeps_each_full_reason_and_no_why():
    g = gift([lead(NP, MW, name="A"), lead(FG, name="B")])
    framing, lines = record_opener(g, Prospect(firm_name="X", city="Atlanta",
                                               state="GA", first_name="Jo"))
    assert framing == ("saw you're based in atlanta. here are 2 nonprofits in atlanta "
                       "that need finance help:")
    assert lines == ["A: auditors flagged their financial controls",
                     "B: first federal grant in 3+ years"]


def test_cost_contracts_claim_every_cost_only_when_every_one_is_cost_reimbursement():
    every = gift([lead(CR, {"pricing_kind": "cost-reimbursement"}, name=n) for n in "AB"])
    assert "where every cost can be audited" in record_opener(every, TROY)[0]
    mixed = gift([lead(CR, {"pricing_kind": "cost-reimbursement"}, name="A"),
                  lead(CR, {"pricing_kind": "time-and-materials"}, name="B")])
    framing, lines = record_opener(mixed, TROY)
    assert "won federal contracts the government can audit, so each needs books that " \
        "can pass a government audit:" in framing
    assert lines == ["A", "B (hourly)"]


def test_one_lead_reads_in_the_singular():
    g = gift([lead(NP, REPEAT, name="Georgia Works")], all_niche=True)
    framing, lines = record_opener(g, TROY)
    assert framing.endswith("this one in atlanta had weak financial controls flagged in "
                            "its federal audit, so it now has to file a plan to fix it:")
    body = build_email_1(g, TROY, today=TODAY, pack=pack_for("cfo")).body
    assert "\n\nGeorgia Works (two years in a row)\n\n" in body   # unnumbered


def test_non_record_leads_keep_the_legacy_path():
    g = gift([lead("job_finance_lead", name="A")])
    assert record_opener(g, TROY) is None


def test_an_old_audit_had_to_file_a_plan_not_now():
    """2026-10-25: a FY2024 audit accepted in early 2025 read "each now has to
    file a plan". One audit over a year old puts the whole sentence in the past."""
    g = gift([lead(NP, MW, name="A"), lead(NP, {**MW, **OLD}, name="B")], all_niche=True)
    framing, _ = record_opener(g, TROY)
    assert framing.endswith("so each had to file a plan to fix it:")
    one = gift([lead(NP, {"fac_material_weakness": True}, name="C")], all_niche=True)
    # A record that does not say when it was filed never claims "now".
    assert record_opener(one, TROY)[0].endswith("so it had to file a plan to fix it:")


def test_the_engineer_line_names_organizations_only_for_nonprofits():
    from system_b.copy.email import left_field_for
    cfo = pack_for("cfo")
    charities = gift([lead(NP, MW, name="A"), lead(NP, MW, name="B")])
    builders = gift([lead(DB, {}, name="A", industry="construction"),
                     lead(NP, MW, name="B")])
    assert left_field_for(cfo, charities) == (
        "i'm an engineer. i built a system that finds organizations like these, "
        "for fractional cfos.")
    assert left_field_for(cfo, builders) == (
        "i'm an engineer. i built a system that finds companies like these, "
        "for fractional cfos.")
    assert left_field_for(pack_for("finance"), builders).endswith("for finance firms.")
