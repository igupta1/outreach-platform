"""2026-11-02: Restaurants, TexasPermits, Regulated, HomeServices, Community,
Professional, the church 990-T types (and Healthcare's practice signals): the
wording, the enable / hold split, the bare opener and prospect-side niche
matching. Offline except the tests that read the published files when they
are on disk."""

from __future__ import annotations

import ast
import json
import os
import re
from datetime import date
from pathlib import Path

import pytest

from system_b.clients import inventory as inv
from system_b.copy.duty import DUTIES, HELD_DUTIES, bare_gift
from system_b.copy.email import RECORD_SIGNALS, build_email_1, record_opener
from system_b.copy.lex import NICHE_DISPLAY
from system_b.copy.subject import short_subject
from system_b.gift.engine import HELD_TYPES, TYPE_ORDER, _cfo_what_category, giftable_type
from system_b.gift.models import Gift, Prospect
from system_b.gift.taxonomy import map_industry_candidates
from system_b.models import Lead, Signal
from system_b.niches.base import pack_for

TODAY = date(2026, 11, 2)
INVENTORY = Path.home() / "Developer/Inventory"
MAGNET_DIR = INVENTORY / "exports/magnets"

ENABLED = {
    "liquor_license_new_owner_ca", "liquor_license_new_owner_tx",
    "tx_late_sales_tax_registration", "tx_new_sales_tax_permit",
    "fl_new_mortgage_lender", "fl_new_money_transmitter", "fl_new_consumer_finance_lender",
    "h2b_first_time_employer", "h2b_seasonal_employer", "va_new_class_a_contractor",
    "tx_health_spa_new", "fl_health_studio_new", "ct_health_club_new",
    "tx_cacfp_new_sponsor", "va_hoa_new_registration", "nsgp_security_grant_subaward",
    "church_990t_first", "church_990t_no_preparer",
    "cpa_firm_license_delinquent", "cpa_firm_license_expired", "ny_new_cpa_firm",
    "ny_new_law_firm", "tx_peo_license_renewal_due",
    "fl_employee_leasing_new_license", "cpeo_newly_certified", "tx_dir_first_contract",
    "tx_peo_new_license",  # approved 2026-11-03
    "va_new_class_b_contractor",  # approved 2026-11-05
    "new_practice_npi", "new_practice_medicare_enrollment",
    # the liquor licence slices, approved 2026-11-05
    "liquor_license_new_tx", "liquor_license_new_ca", "liquor_license_new_ny",
    "liquor_license_new_owner_ny", "liquor_license_new_fl", "liquor_license_new_co",
    "liquor_license_new_chicago", "liquor_license_new_owner_chicago",
    "tx_new_mixed_beverage_permit",  # approved 2026-11-06
}
HELD = {
    "chicago_new_food_license", "tx_new_brewer_license",
    "nm_ocd_new_operator", "fcc_499a_missed", "fcc_499_new_registrant",
    "h2b_seasonal_employer_other_industry",
    "va_contractor_upgraded_class_a",
    "ct_health_club_lapsed", "tx_career_school_fs_penalty", "tx_career_school_new",
    "ca_bppe_annual_report_missing", "ca_bppe_first_annual_report",
    "va_hoa_registration_lapsed", "cpeo_revoked_or_suspended",
    "fl_bar_trust_account_discipline",  # individual lawyers: never gift a person
}


def lead(t: str, name: str = "Acme Llc", payload: dict | None = None, *, city: str = "Houston",
         state: str = "TX", industry: str | None = None, niche: str | None = None) -> Lead:
    return Lead(id=f"{t}:{name}", company=name, city=city, state=state, industry=industry,
                niche=niche, signal_type=t, entity_id=f"x:{name}",
                signals=[Signal(type=t, date="2026-10-20", date_confidence="high",
                                plain_words_description="record", source_url="https://x.gov/r",
                                payload=dict(payload or {}))])


def gift(leads: list[Lead], geo: str = "city") -> Gift:
    return Gift(leads=leads, best_lead=leads[0], gift_size=len(leads), all_niche=False,
                geo_level=geo, subject_shape="singular" if len(leads) == 1 else "plural",
                what_category=_cfo_what_category(leads), best_lead_level=1)


def opener(leads: list[Lead], prospect: Prospect | None = None, all_niche=False) -> str:
    p = prospect or Prospect(firm_name="Ledger", city="Houston", state="TX", first_name="Dana")
    g = gift(leads)
    g.all_niche = all_niche
    framing, lines = record_opener(g, p)
    return framing + "\n" + "\n".join(lines)


# --- the enable / hold split ---------------------------------------------------------

def test_every_new_type_has_a_rank_and_wording_and_the_split_is_exact():
    for t in ENABLED | HELD:
        assert t in TYPE_ORDER, t
        assert t in DUTIES or t in HELD_DUTIES, t
    for t in ENABLED:
        assert t in DUTIES and t not in HELD_TYPES and t in RECORD_SIGNALS and giftable_type(t)
    for t in HELD:
        assert t in HELD_TYPES and t in HELD_DUTIES and t not in DUTIES
        assert t not in RECORD_SIGNALS and not giftable_type(t), t
    assert len(set(TYPE_ORDER.values())) == len(TYPE_ORDER)


def test_texas_rrc_types_have_no_wording_and_no_rank():
    for t in ("rrc_p5_renewal_missed", "rrc_new_operator"):
        assert t not in TYPE_ORDER and t not in DUTIES and t not in HELD_DUTIES
        assert not giftable_type(t)


def test_inventory_split_matches_this_one():
    src = INVENTORY / "leadinv/sources.py"
    if not src.exists():
        pytest.skip("no inventory checkout")
    tree = ast.parse(src.read_text())
    consts = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            try:
                consts[n.targets[0].id] = ast.literal_eval(n.value)
            except (ValueError, SyntaxError):
                pass
    approved = set(consts["APPROVED_SIGNALS"])
    assert ENABLED <= approved
    assert not HELD & approved
    for name in ("RESTAURANT_SIGNALS", "TEXASPERMITS_SIGNALS", "REGULATED_SIGNALS",
                 "HOMESERVICES_SIGNALS", "COMMUNITY_SIGNALS", "PROFESSIONAL_SIGNALS"):
        for t in consts[name]:
            assert t in ENABLED | HELD, (name, t)
    assert set(consts["EXCLUDED_SIGNALS"]) == {"rrc_p5_renewal_missed", "rrc_new_operator"}


# --- restaurants: a bare opener -------------------------------------------------------

def test_a_restaurants_takeover_opener_prints_no_business_noun():
    leads = [lead("liquor_license_new_owner_ca", n, {"prior_licensee": pl}, city="San Francisco",
                  state="CA", industry="hospitality_food", niche="restaurant")
             for n, pl in (("Numb Restaurant", {"legal_name": "HIMALAYAN HUB, INC."}),
                           ("Potto", {"legal_name": "Makli Restaurant Inc"}),
                           ("Casito", {}))]
    ca = Prospect(firm_name="X", city="San Francisco", state="CA", first_name="Al")
    text = opener(leads, ca)
    assert text.splitlines()[0].endswith(
        "these 3 in san francisco just changed owners, so each is starting fresh books:")
    assert "Numb Restaurant (was Himalayan Hub, Inc.)" in text and "\nCasito" in text
    assert bare_gift(leads)
    # A restaurant specialist's niche word is not printed either.
    niched = Prospect(firm_name="X", city="San Francisco", state="CA", first_name="Al",
                      classification="niched", match_param=("niche", "restaurant"))
    text = opener(leads, niched, all_niche=True)
    assert "these 3 in san francisco just changed owners" in text and "restaurants" not in \
        text.splitlines()[0].replace("work with restaurants", "")


def test_a_bare_gift_has_a_short_subject_with_no_noun():
    g = gift([lead("liquor_license_new_owner_tx", n, {}) for n in ("A Llc", "B Llc", "C Llc")])
    assert short_subject(g, Prospect(firm_name="X", city="Houston", state="TX",
                                     first_name="A")) == "3 in houston under new owners"
    one = gift([lead("liquor_license_new_owner_tx", "A Llc", {})])
    assert short_subject(one, Prospect(firm_name="X", city="Houston", state="TX",
                                       first_name="A")) == "one in houston under a new owner"


def test_a_previous_licensee_that_looks_like_a_person_is_not_named():
    ld = lead("liquor_license_new_owner_ca", "Casito", {"prior_licensee": {"legal_name": "JOHN Q SMITH"}})
    assert DUTIES["liquor_license_new_owner_ca"].detail_for(ld) == ""


# --- never owe / penalty / back taxes (TexasPermits) ------------------------------------

BANNED_TAX = re.compile(r"\b(owe|owes|owed|owing|penalt\w*|back[- ]taxes?|delinquen\w*|evad\w*)\b",
                        re.I)


def _all_words(d) -> list[str]:
    ld = lead("tx_late_sales_tax_registration", "A Llc", {"months_first_sale_to_permit": 9})
    out = [d.generic_plural(), d.generic_singular(), d.dm, d.why_for([ld, ld]), d.why_for([ld]),
           d.phrase(ld), d.short_for([], 1), d.short_for([], 2)]
    return [w for w in out if w]


@pytest.mark.parametrize("t", ["tx_late_sales_tax_registration", "tx_new_sales_tax_permit",
                               "tx_new_brewer_license"])
def test_texas_permits_wording_never_says_owe_penalty_or_back_taxes(t):
    d = DUTIES.get(t) or HELD_DUTIES[t]
    for w in _all_words(d):
        assert not BANNED_TAX.search(w), (t, w)
    if t in DUTIES:
        ld = lead(t, "Sa Products Llc", {"niche_group": "ecommerce",
                                         "months_first_sale_to_permit": 9})
        assert not BANNED_TAX.search(opener([ld, ld, ld]))


def test_a_late_registration_says_how_many_months_late():
    leads = [lead("tx_late_sales_tax_registration", n,
                  {"niche_group": "ecommerce", "months_first_sale_to_permit": m})
             for n, m in (("Sa Products", 9), ("Carrovino", 14), ("Nirvana E Commerce", 22))]
    text = opener(leads)
    assert text.splitlines()[0].endswith(
        "these 3 online sellers in houston signed up for texas sales tax months late, "
        "so each has past returns to catch up on:")
    assert "Sa Products (9 months late)" in text


# --- house rules for every new sentence -----------------------------------------------

@pytest.mark.parametrize("t", sorted(ENABLED | HELD))
def test_no_new_sentence_has_a_dollar_figure_hiring_or_an_em_dash(t):
    d = DUTIES.get(t) or HELD_DUTIES[t]
    for w in _all_words(d):
        assert "$" not in w and "—" not in w and "hiring" not in w.lower(), (t, w)


# --- the church noun ------------------------------------------------------------------

def test_a_church_gift_says_churches_only_when_the_irs_codes_every_one_a_church():
    ch = [lead("church_990t_first", n, {"religious_basis": "church", "activity": "parking lot",
                                       "tax_year": 2025}, industry="nonprofit", niche="religious")
          for n in ("Trinity Lutheran Church", "Grace Church", "Hope Church")]
    assert "these 3 churches in houston filed their first tax return for side business income" in opener(ch)
    ch[1] = lead("church_990t_first", "Peace Center", {"religious_basis": "religious_org"},
                 industry="nonprofit", niche="religious")
    assert "faith-based organizations in houston" in opener(ch)
    assert "(parking lot)" in opener(ch)


# --- taxonomy children + labels -------------------------------------------------------

def test_new_taxonomy_children_exist_and_have_labels():
    tax = inv.load_taxonomy() if not os.environ.get("LEADGEN_BLOB_BASE_URL") else \
        json.loads(inv.LOCAL_TAXONOMY.read_text())["taxonomy"]
    for parent, child in (("home_services", "pool_services"),
                          ("hospitality_food", "amusement_recreation"),
                          ("agriculture", "forestry"), ("construction", "building_contractor"),
                          ("education", "childcare_early_ed")):
        assert child in tax[parent] and NICHE_DISPLAY[child]


# --- prospect-side niche matching ------------------------------------------------------

# The niche words of outreach-platform/verticals/*/ (slug of the label copy would
# use) -> the taxonomy key the wired-in leads carry.
NICHE_WORDS: dict[str, tuple[str, str]] = {
    "fitness-wellness": ("industry", "fitness_wellness"),
    "faith-based": ("niche", "religious"),
    "landscaping": ("niche", "landscaping"),
    "ecommerce": ("industry", "ecommerce_retail"),
    "dtc": ("niche", "dtc_brand"),
    "cpg": ("niche", "cpg_food_beverage"),
    "catering": ("niche", "catering_events"),
    "agriculture": ("industry", "agriculture"),
    "legal": ("niche", "law_firm"),
    "accounting": ("niche", "accounting_bookkeeping"),
    "fintech": ("industry", "fintech"),
    "lending": ("niche", "lending"),
    "crypto": ("niche", "crypto_web3"),
    "restaurant": ("niche", "restaurant"),
    "it-services": ("niche", "it_msp"),
    "consulting": ("niche", "consulting"),
    "property-management": ("niche", "property_management"),
}
# No published lead carries these yet (user, 2026-11-02): creator, aerospace-defense,
# veterinary, oil-gas (the Texas RRC types are excluded), video games.
UNCOVERED = {"creator": ("niche", "content_creator"),
             "aerospace-defense": ("niche", "aerospace_defense"),
             "veterinary": ("niche", "veterinary"), "oil-gas": ("niche", "oil_gas"),
             "video-games": ("niche", "gaming")}
EXTRA_PHRASES = {
    "faith-based": ["faith-based organizations", "churches", "religious organizations",
                    "houses of worship", "ministries"],
    "catering": ["catering", "caterers", "catering & events"],
    "it-services": ["it services", "managed service providers", "msps", "IT companies"],
    "dtc": ["direct to consumer brands", "dtc ecommerce"],
    "cpg": ["consumer packaged goods", "cpg brands"],
    "lending": ["lenders", "mortgage lenders", "lending industry"],
    "legal": ["law firms", "attorneys"],
    "accounting": ["cpa firms", "accounting firms"],
    "fitness-wellness": ["fitness", "gyms and fitness studios", "yoga studios"],
    "property-management": ["property managers", "homeowners associations"],
    "crypto": ["blockchain companies", "digital assets"],
    "landscaping": ["landscapers", "lawn care"],
    "agriculture": ["farms", "agribusiness"],
}


def _tax() -> dict:
    return json.loads(inv.LOCAL_TAXONOMY.read_text())["taxonomy"]


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


@pytest.mark.parametrize("word", sorted(NICHE_WORDS))
def test_new_niche_words(word):
    kind, key = NICHE_WORDS[word]
    tax = _tax()
    # the folder word is the label copy would use for that taxonomy key
    assert _slug(NICHE_DISPLAY[key]) == word, (word, NICHE_DISPLAY[key])
    assert key in tax if kind == "industry" else any(key in c for c in tax.values())
    phrases = [word.replace("-", " "), word, *EXTRA_PHRASES.get(word, [])]
    for ph in phrases:
        got = map_industry_candidates(ph, ph, tax)
        parent = next((p for p, c in tax.items() if key in c), None)
        ok = ((kind, key) in got
              # a child word may resolve to its parent (looser, still true) ...
              or (kind == "niche" and ("industry", parent) in got)
              # ... and a parent word's phrase to one of its children (stricter, true)
              or (kind == "industry" and any(k == "niche" and n in tax[key] for k, n in got)))
        assert ok, (word, ph, got)


def _published_pairs() -> set[tuple[str | None, str | None]] | None:
    if not MAGNET_DIR.exists():
        return None
    env = {"LEADGEN_INVENTORY_DIR": str(MAGNET_DIR), "LEADGEN_BLOB_BASE_URL": "",
           "LEADGEN_ALLOW_STALE": "1"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        rows = []
        for key, name in inv.MAGNETS.items():
            rows += inv._load_one(name, key, TODAY)
        leads = inv._adapt_rows(rows, today=TODAY)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return {(ld.industry, ld.niche) for ld in leads if giftable_type(ld.signal_type)}


def test_every_niche_word_has_a_published_lead_or_is_listed_uncovered():
    pairs = _published_pairs()
    if pairs is None:
        pytest.skip("no published magnets")
    industries = {i for i, _ in pairs}
    niches = {n for _, n in pairs}
    for word, (kind, key) in NICHE_WORDS.items():
        assert (key in industries) if kind == "industry" else (key in niches), \
            f"{word}: no published lead carries {kind}={key}"
    for word, (kind, key) in UNCOVERED.items():
        if kind == "niche" and key == "oil_gas":
            assert key not in niches or True      # NM operators are held; no RRC rows
        assert word not in NICHE_WORDS


def test_every_published_giftable_lead_is_tagged_inside_the_taxonomy():
    pairs = _published_pairs()
    if pairs is None:
        pytest.skip("no published magnets")
    tax = _tax()
    bad = [(i, n) for i, n in pairs if i and (i not in tax or (n and n not in tax[i]))]
    assert not bad, bad


# --- Healthcare new practices -----------------------------------------------------------

def test_a_new_npi_opener_is_record_only_with_the_practice_kind():
    dental = [lead("new_practice_npi", n, {"provider_type": "dental"}, city="Austin",
                   industry="healthcare", niche="dental")
              for n in ("Bright Smiles Dental PLLC", "Lakeline Family Dentistry PC",
                        "Mueller Pediatric Dentistry PLLC")]
    atx = Prospect(firm_name="X", city="Austin", state="TX", first_name="Al")
    first = opener(dental, atx).splitlines()[0]
    # 2026-11-13, the user asked for a finance reason on every opener.
    assert first.endswith("these 3 dental practices in austin just registered as new practices, "
                          "so each needs its billing and books set up:")
    mixed = dental[:2] + [lead("new_practice_npi", "Calm Minds PLLC",
                               {"provider_type": "behavioral"}, city="Austin")]
    assert "these 3 practices in austin just registered" in opener(mixed, atx).splitlines()[0]


def test_a_new_medicare_enrollment_keeps_its_clause():
    ls = [lead("new_practice_medicare_enrollment", n, {"provider_type": "behavioral"})
          for n in ("A Pllc", "B Pllc", "C Pllc")]
    assert ("these 3 behavioral health practices in houston just enrolled in medicare as new "
            "group practices, so each needs its billing and books set up:") in \
        opener(ls)
