"""Step 3 — build the gift (pure logic).

3a fractional-CFO check, 3b two-round Level 1-5 walk, 3c count, 3d best
lead, 3e honesty values. Geography-first: gift is assembled by match
level; signal type then date are tiebreaks WITHIN a level (except 3a).

Order (2026-10-18, the user's rules): the match level always decides first
(industry + area; the walk itself is unchanged, and so are Gates A and B).
Within a level `sort_key`: the pack's `signal_rank` -> a lead suiting the
firm's CLEAR focus (`Prospect.focus`, only when its site is plainly one kind of
work) -> `TYPE_ORDER` across the magnets -> findable -> the lead's score
(within a type) -> newest -> date confidence. `_best_lead`: rank ->
TYPE_ORDER -> domain -> score -> freshness -> match level.

2026-10-30 (measured over the 1,107 unsent prospects, see `_pick_leads`):
inside the prospect's own state a stronger BAND of lead beats a closer place
(`STRENGTH_BEATS_CITY`); past the own state come strong leads from the
bordering states, then strong leads nationwide (`FAR_LEVELS`); Row 8 (new
businesses) is off (`ROW8_IN_GIFTS`); a held or unworded type never enters a
gift (`giftable`).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime
from typing import Any, Protocol

from system_b import config
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead
from system_b.niches.base import NichePack, default_pack

log = logging.getLogger("system_b.gift")

# Strongest -> weakest, in leadgen's raw signal-type vocabulary. This is the CFO
# pack's rank (imported by niches/cfo.py); every pack now supplies its own
# `signal_rank`, which the tiebreak sorts read via the `rank` arg. A lead whose
# signal isn't in the active rank map ranks last (9).
SIGNAL_RANK: dict[str, int] = {
    "job_fractional_cfo": 0,
    "job_finance_lead": 1,
    "funding_form_d": 2,
}
# Funding signal types (SEC Form D/C) — a lead whose primary signal is one of
# these is a "raise" for copy/what-category purposes.
FUNDING_SIGNALS: frozenset[str] = frozenset({"funding_form_d", "funding_form_c"})
GIFT_TARGET = 3

_US_STATES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh", "oklahoma": "ok",
    "oregon": "or", "pennsylvania": "pa", "rhode island": "ri",
    "south carolina": "sc", "south dakota": "sd", "tennessee": "tn", "texas": "tx",
    "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
    "district of columbia": "dc", "puerto rico": "pr",
}


# Strength order ACROSS the magnets' signal types (strongest first), applied
# after the pack's own `signal_rank` (job types) and before the lead's score,
# which orders leads WITHIN a type (each source scores on its own scale, and
# the inventory's 0-100 strength is a percentile within the type). An audit
# finding a CPA signed is the strongest public evidence of a finance problem;
# a fresh registration says the least. Types not listed sit just above the
# new-business rows.
#
# 2026-10-27: the legal-duty types (`copy.duty`) slot in by how strong a
# duty their record proves, keeping the original six in their order:
#   1. an auditor or a regulator flagged a problem that has to be fixed;
#   2. Davis-Bacon and cost-type awards (the original strong pair);
#   3. a duty just switched on, with a deadline (first plan audit, first
#      cost report, excise returns, a yearly audit for a new program);
#   4. a required report late or missing on the record;
#   5. a tax debt or a plan problem the filer itself reported;
#   6. the original grant / license rows, then everything else, then Row 8.
# Each type keeps its own rank, so a gift fills from one kind first and the
# record opener can say it once.
_TYPE_STRENGTH: tuple[str, ...] = (
    "nonprofit_grant_no_finance_officer",           # charity audit problems
    # 1. flagged by an auditor or a regulator
    "nonprofit_questioned_costs", "nonprofit_going_concern",
    "nonprofit_single_audit_not_done", "bd_material_weakness", "restatement_nonreliance",
    "plan_audit_opinion_modified", "college_heightened_cash_monitoring",
    "ny_omig_final_audit", "nonprofit_asset_diversion", "plan_fraud_loss",
    "ca_dre_trust_fund_discipline", "nc_rec_trust_account_discipline",
    # a Florida Supreme Court order over trust-account misconduct (2026-11-02)
    "fl_bar_trust_account_discipline",
    "ca_dre_audit_discipline", "union_funds_shortage",
    # 2. the original strong pair
    "construction_federal_award_davis_bacon",       # federal construction award
    "federal_cost_reimbursement_contract",          # cost-type federal contract
    # 3. a duty just switched on
    "plan_audit_first_due", "welfare_plan_audit_threshold", "medicare_new_part_a_provider",
    "snf_change_of_ownership", "hospital_change_of_ownership", "hrsa_new_health_center",
    "nsgp_security_grant_subaward",     # federal grant rules start with the award
    "cu_over_500m_no_fs_audit", "cu_stale_audit", "wi_choice_school_new",
    "tx_career_school_new", "tx_cacfp_new_sponsor",
    "construction_first_prevailing_wage_intent", "hud_new_owner",
    "ttb_new_distillery_permit", "ttb_new_winery_permit",
    # 2026-11-02: federal excise returns start with a brewer's licence (the
    # same duty as TTB's), a Texas mixed beverage permit starts monthly tax
    # reports (held), and the PEO / employee-leasing / CPEO licences each carry
    # a CPA-audited financial-statement duty that starts with the licence.
    "tx_new_brewer_license", "tx_new_mixed_beverage_permit",
    "cpeo_newly_certified", "fl_employee_leasing_new_license", "tx_peo_new_license",
    "tx_peo_license_renewal_due", "tx_dir_first_contract",
    "cannabis_new_license", "cannabis_began_operations",
    # 2026-11-02, by what the record proves: a Florida money transmitter is the
    # only one with an annual audit duty, so it leads; H-2B's first application
    # is an agreement to wage, hours and pay-record rules; health clubs (FL
    # first: bond + issue date + email; TX's date is inferred).
    "fl_new_money_transmitter", "fl_new_mortgage_lender", "fl_new_consumer_finance_lender",
    "nm_ocd_new_operator", "fcc_499_new_registrant",
    "h2b_first_time_employer",
    "fl_health_studio_new", "tx_health_spa_new", "ct_health_club_new",
    "nv_casino_new_nonrestricted_license", "film_ca_credit_allocated",
    "film_nj_credit_approved", "ae_caltrans_first_icr_acceptance",
    "fl_condo_new_association", "va_hoa_new_registration", "plan_audit_first_filed",
    # 4. a required report late or missing (a charity two years without a 990
    # first: one more year and its exemption is revoked by law)
    "nonprofit_990_missed_2yr", "nonprofit_single_audit_late", "nonprofit_990_missed_1yr",
    # months of sales-tax returns due before the permit existed (2026-11-02)
    "tx_late_sales_tax_registration",
    "local_gov_single_audit_late", "late_filing_notice",
    "nasdaq_late_filing_deficiency", "rega_tier2_1k_missing", "adv_annual_amendment_overdue",
    "bd_annual_audit_late", "tx_career_school_fs_penalty",
    "charter_audit_missing", "ca_bppe_annual_report_missing",
    "water_ca_annual_report_missing", "va_hoa_registration_lapsed",
    "union_lm_report_late", "fcc_499a_missed",
    "local_gov_financial_report_late", "ae_txdot_overhead_approval_lapsed",
    "ct_health_club_lapsed", "cpa_firm_license_delinquent", "cpa_firm_license_expired",
    "proprietary_90_10_near_limit", "auditor_change", "cu_approaching_fs_audit",
    # 5. tax debts and self-reported plan or 990 problems
    "federal_tax_lien", "state_tax_lien", "unemployment_tax_lien", "top_tax_delinquent",
    "cannabis_licensee_tax_delinquent", "cannabis_tax_report_violation",
    "cannabis_recordkeeping_violation", "cannabis_traceability_violation",
    "cannabis_license_suspended",
    "construction_fl_stop_work_order", "pension_unpaid_min_contribution",
    "plan_prohibited_transaction", "nonprofit_ubi_no_990t", "nonprofit_excess_benefit",
    "nonprofit_exemption_revoked", "nonprofit_state_audit_line_no_audit",
    # a deficit two years running with under a month of cash, from the 990 itself
    # (2026-11-03): the org's own admission, so it sits with the 990 problems
    "nonprofit_deficit_low_cash",
    "plan_late_contributions", "plan_termination_pending",
    "cpeo_revoked_or_suspended",        # no reason on the IRS list (2026-11-02)
    # 6. the original weaker rows (Funds' absence first: re-added 2026-10-30)
    "adv_no_fund_administrator",
    "federal_first_time_grant", "govcon_first_sbir_phase2", "tcac_placed_in_service",
    "va_contractor_upgraded_class_a",
    "construction_license_upgrade", "construction_nv_license_limit",
    # licence / registration rows (2026-11-02): a new filing duty, but the
    # softest kind. Restaurants' takeovers first, then its new licences.
    "liquor_license_new_owner_ca", "liquor_license_new_owner_tx",
    "liquor_license_new_owner_ny", "liquor_license_new_owner_chicago",
    "liquor_license_new_tx", "liquor_license_new_ca", "liquor_license_new_ny",
    "liquor_license_new_fl", "liquor_license_new_co", "liquor_license_new_chicago",
    "chicago_new_food_license",
    # Healthcare (2026-11-02): an approved Medicare group enrollment is stated by
    # the record itself, so it ranks with the licence rows; a first organization
    # NPI is the softest event of all (last, after the Form D rows).
    "new_practice_medicare_enrollment",
    "va_new_class_a_contractor", "h2b_seasonal_employer", "va_new_class_b_contractor",
    "h2b_seasonal_employer_other_industry", "tx_new_sales_tax_permit",
    "construction_new_licensed_business",
    "ny_new_law_firm", "ny_new_cpa_firm",
    # a first 990-T is a duty that just switched on (above the first 990, the
    # same kind of event with no tax attached); no preparer is an ongoing duty
    # the church handles itself (below the new-org rows). Churches file no 990.
    "church_990t_first",
    # a new nonprofit: its first annual return, then a new 501(c)(3)
    "nonprofit_first_990", "nonprofit_new_501c3",
    "church_990t_no_preparer", "ca_bppe_first_annual_report",
    # a tech company's new Form D (2026-10-30): an event, no duty
    "startup_first_form_d", "startup_new_form_d",
    "new_practice_npi",
)
TYPE_ORDER: dict[str, int] = {t: i for i, t in enumerate(_TYPE_STRENGTH)}

# HELD (2026-10-29): types whose wording is written (`copy.duty.HELD_DUTIES`)
# but not yet approved by the user. They keep their rank above, but are no
# record signal: no gift, opener, subject or DM uses one. The inventory holds
# them back too (its `sources.APPROVED_SIGNALS` leaves them out, so `publish`
# never sends one). To approve a type: delete it here AND add it to the
# inventory's APPROVED_SIGNALS (`test_duty_copy` checks the two agree).
# OUTREACH_PREVIEW_HELD=1 lifts the hold for a local preview run only.
# Empty since 2026-10-30: the 990 filing gaps and the two new-nonprofit types
# (`nonprofit_new_501c3`, `nonprofit_first_990`) were approved.
# 2026-10-30: Funds' `adv_annual_amendment_overdue` (wording drafted, not approved).
# Cannabis traceability citations and suspensions (2026-10-30): held by decision.
# 2026-11-02: the wired-in sources' held slices (Inventory sources.py says why
# each is held): Restaurants' new-licence slices, mixed beverage permits,
# Chicago food licences and the NY / Chicago takeovers; TexasPermits' brewer;
# Regulated's NM operators and both FCC types; HomeServices' Class B, repeat
# H-2B outside home services / construction and Class A upgrades; Community's
# CT lapsed clubs, career schools, BPPE and VA lapsed registrations;
# Professional's TX PEO new licences and CPEO revocations. The Texas RRC types
# are not here at all: the Inventory never ingests them (terms allow
# noncommercial use only).
_HELD: frozenset[str] = frozenset({"adv_annual_amendment_overdue",
                                   "cannabis_traceability_violation",
                                   "cannabis_license_suspended",
                                   # Restaurants
                                   "tx_new_mixed_beverage_permit", "liquor_license_new_tx",
                                   "liquor_license_new_ca", "liquor_license_new_ny",
                                   "liquor_license_new_owner_ny", "liquor_license_new_fl",
                                   "liquor_license_new_co", "liquor_license_new_chicago",
                                   "liquor_license_new_owner_chicago",
                                   "chicago_new_food_license",
                                   # TexasPermits
                                   "tx_new_brewer_license",
                                   # Professional: leads are individual lawyers
                                   "fl_bar_trust_account_discipline",
                                   # Regulated
                                   "nm_ocd_new_operator", "fcc_499a_missed",
                                   "fcc_499_new_registrant",
                                   # HomeServices
                                   "va_new_class_b_contractor",
                                   "h2b_seasonal_employer_other_industry",
                                   "va_contractor_upgraded_class_a",
                                   # Community
                                   "ct_health_club_lapsed", "tx_career_school_fs_penalty",
                                   "tx_career_school_new", "ca_bppe_annual_report_missing",
                                   "ca_bppe_first_annual_report", "va_hoa_registration_lapsed",
                                   # Professional
                                   "tx_peo_new_license", "cpeo_revoked_or_suspended"})
HELD_TYPES: frozenset[str] = frozenset() if os.environ.get("OUTREACH_PREVIEW_HELD") else _HELD
_OTHER_TYPE = len(_TYPE_STRENGTH)
TYPE_ORDER.update({"new_business_formed": _OTHER_TYPE + 1,
                   "new_business_expanding": _OTHER_TYPE + 2})

# Row 8 is a BACKUP: a gift is built from every other lead type first, and a
# new business only fills a place nothing else could (see `_pick_leads`).
BACKUP_PREFIX = "new_business_"

# Row 8 in gifts at all (2026-10-30: off; the user dislikes it). Measured over
# the 1,107 unsent prospects against the 2026-10-30 inventory, with and without
# the old one-organization-per-state rule: 0 gifts used a new business and
# every US prospect's gift still reached 3 leads without one. It filled 42% of
# gifts only while the inventory was the original five magnets AND that rule
# was on (both gone since 2026-10-27 / 10-25). True puts it back as the very
# last round, after the far levels.
ROW8_IN_GIFTS = False


def is_backup(lead: Lead) -> bool:
    return (lead.signal_type or "").startswith(BACKUP_PREFIX)


# --- strength bands (2026-10-30) -------------------------------------------
#
# Three coarse bands over `_TYPE_STRENGTH`, cut at the first type of its
# groups 3 and 5, so a type added INSIDE a group lands in that group's band:
#   STRONG  an auditor or regulator flagged it; Davis-Bacon; cost-type contract
#   MEDIUM  a duty just switched on; a required report late or missing
#   WEAK    tax debts, self-reported problems, grants, licenses, new orgs,
#           anything unlisted, Row 8
# Used where a closer place used to win outright: inside the prospect's own
# state (`STRENGTH_BEATS_CITY`) and in the far levels (`FAR_LEVELS`).
_MEDIUM_FROM = "plan_audit_first_due"
_WEAK_FROM = "federal_tax_lien"
STRONG, MEDIUM, WEAK = 0, 1, 2


def strength_band(lead: Lead) -> int:
    order = TYPE_ORDER.get(lead.signal_type or "", _OTHER_TYPE)
    if order < TYPE_ORDER[_MEDIUM_FROM]:
        return STRONG
    if order < TYPE_ORDER[_WEAK_FROM]:
        return MEDIUM
    return WEAK


# Inside the prospect's own state, a WEAK lead in their city no longer beats a
# stronger one elsewhere in their state: the walk used to take every lead in
# the city first. Strong and medium city leads keep their place, and within a
# band the city still comes first. The copy stays honest on its own:
# `_honesty` says "city" only when every lead is there, else "state".
# Measured 2026-10-30 (1,107 unsent prospects, no allocation limit):
#   generalist gifts with a weak lead (tax lien, late plan contribution,
#   license, new nonprofit)           20% -> 0%
#   generalist gifts that name the city        90% -> 73%
#   charity-audit share of generalist leads    46% -> 58%
# CITY_YIELDS_FROM = MEDIUM would also let a strong state lead beat a medium
# city lead: 100% strong leads, but only 47% of generalist gifts keep the city.
STRENGTH_BEATS_CITY = True
CITY_YIELDS_FROM = WEAK

# Past the prospect's own state (2026-10-30, replacing Row 8): strong leads
# from the bordering states, then strong leads from anywhere. Only STRONG band
# leads (a lead from away has to earn its place: the email loses its "in
# <city>" line), except when `signal_types` narrows the walk to email 1's
# kind, which already decides. Only for a prospect in a US state. A gift that
# reaches here has geo_level "none", so no copy names their city or state.
FAR_LEVELS = True
LEVEL_NEARBY, LEVEL_NATIONWIDE = 6, 7

_BORDERS = (
    "al fl", "al ga", "al ms", "al tn", "az ca", "az co", "az nm", "az nv", "az ut",
    "ar la", "ar mo", "ar ms", "ar ok", "ar tn", "ar tx", "ca nv", "ca or",
    "co ks", "co ne", "co nm", "co ok", "co ut", "co wy", "ct ma", "ct ny", "ct ri",
    "de md", "de nj", "de pa", "dc md", "dc va", "fl ga", "ga nc", "ga sc", "ga tn",
    "id mt", "id nv", "id or", "id ut", "id wa", "id wy", "il ia", "il in", "il ky",
    "il mo", "il wi", "in ky", "in mi", "in oh", "ia mn", "ia mo", "ia ne", "ia sd",
    "ia wi", "ks mo", "ks ne", "ks ok", "ky mo", "ky oh", "ky tn", "ky va", "ky wv",
    "la ms", "la tx", "me nh", "md pa", "md va", "md wv", "ma nh", "ma ny", "ma ri",
    "ma vt", "mi oh", "mi wi", "mn nd", "mn sd", "mn wi", "ms tn", "mo ne", "mo ok",
    "mo tn", "mt nd", "mt sd", "mt wy", "ne sd", "ne wy", "nv or", "nv ut", "nh vt",
    "nj ny", "nj pa", "nm ok", "nm tx", "nm ut", "ny pa", "ny vt", "nc sc", "nc tn",
    "nc va", "nd sd", "oh pa", "oh wv", "ok tx", "or wa", "pa wv", "sd wy", "tn va",
    "ut wy", "va wv",
)
ADJACENT_STATES: dict[str, frozenset[str]] = {s: frozenset() for s in _US_STATES.values()}
for _pair in _BORDERS:
    _a, _b = _pair.split()
    ADJACENT_STATES[_a] = ADJACENT_STATES[_a] | {_b}
    ADJACENT_STATES[_b] = ADJACENT_STATES[_b] | {_a}


# Types a gift may carry. An inventory type outreach has no words for would
# otherwise rank "just above Row 8" and render through the job-post path
# ("hiring finance leadership"), and a HELD type is worded but not approved.
# Either is skipped and logged once, whatever the inventory publishes
# (2026-10-30: the inventory moves ahead of outreach as sources are wired).
_LEGACY_PREFIXES = ("job_", "breach_")
_SKIPPED_TYPES: set[str] = set()


def giftable_type(st: str, rank: dict[str, int] | None = None) -> bool:
    """A type with approved words: a magnet record or absence, or (the IT
    packs' --legacy-niche inventory) a job, breach or funding signal."""
    if st in HELD_TYPES:
        return False
    return (st in MAGNET_SIGNALS or st in FUNDING_SIGNALS or st in (rank or {})
            or st.startswith(_LEGACY_PREFIXES))


def giftable(lead: Lead, rank: dict[str, int] | None = None) -> bool:
    st = lead.signal_type or ""
    ok = giftable_type(st, rank)
    if not ok and st not in _SKIPPED_TYPES:
        _SKIPPED_TYPES.add(st)
        log.warning("gift: %r leads never enter a gift (%s)", st,
                    "held" if st in HELD_TYPES else "no wording for this type")
    return ok


# The service tags that suit a firm whose site is plainly about ONE kind of
# work (Prospect.focus, from research.rung.clear_focus). A tiebreak among
# leads at the same match level; a firm is never limited to these.
FOCUS_TAGS: dict[str, frozenset[str]] = {
    "bookkeeping": frozenset({"bookkeeping_setup", "payroll_setup", "bookkeeping"}),
    "accounting": frozenset({"construction_accounting", "govcon_accounting",
                             "grant_accounting", "controls_remediation"}),
    "cfo": frozenset({"fractional_cfo", "controls_remediation", "govcon_accounting"}),
}


def suits_focus(lead: Lead, focus: str | None) -> bool:
    tags = FOCUS_TAGS.get(focus or "")
    return bool(tags) and bool(tags & set(lead.service_tags or ()))


class _Scraper(Protocol):
    def leads(self, **params: Any) -> list[Lead]: ...


def norm_loc(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def norm_state(s: str | None) -> str:
    n = norm_loc(s)
    return _US_STATES.get(n, n)


def _recency(lead: Lead) -> float:
    d = lead.newest_date
    if not d:
        return float("-inf")
    try:
        return datetime.fromisoformat(d[:19]).timestamp()
    except ValueError:
        return float("-inf")


# An audit filed more than this long before the inventory's as-of date is
# "old": its corrective action plan was due when it was filed, so the copy
# says "had to file a plan", not "now has to" (copy.email.record_opener), and
# a newer audit of the same kind is picked first (`sort_key`). 2026-10-25: 10
# of 80 leads in a batch were FY2024 audits accepted in early 2025.
AUDIT_RECENT_DAYS = 365
# How much an old audit's score drops in the walk. A hard "newer first" rule
# put two late filings (scores 45, 21) ahead of three FY2024 findings (95, 91,
# 90) on the same day it shipped; a penalty prefers a newer audit only when
# the two are close. Old findings score a median 47, recent late filings 23.
OLD_AUDIT_PENALTY = 20


def audit_is_recent(lead: Lead) -> bool | None:
    """True when a charity's newest federal audit was accepted within a year of
    the record's own as-of date, False when longer ago, None when the record
    does not say (or the lead is not an audit)."""
    if lead.signal_type != "nonprofit_grant_no_finance_officer":
        return None
    for sig in lead.signals:
        p = getattr(sig, "payload", None) or {}
        filed = p.get("fac_accepted_date") or p.get("fac_first_submitted")
        as_of = p.get("fac_as_of")
        if filed and as_of:
            try:
                age = datetime.fromisoformat(str(as_of)[:10]) - datetime.fromisoformat(str(filed)[:10])
            except ValueError:
                return None
            return age.days <= AUDIT_RECENT_DAYS
    return None


def _recent_finding(lead: Lead) -> bool:
    """A charity whose auditor flagged a problem in an audit filed this year."""
    if audit_is_recent(lead) is not True:
        return False
    return any(any((getattr(sig, "payload", None) or {}).get(k) for k in _NONPROFIT_FINDINGS)
               for sig in lead.signals)


def strength(lead: Lead) -> float:
    """The order the walk uses inside a band and a type, and the order an email
    lists its leads in: the inventory's pain score where the file has one
    (2026-11-03; its recency part already ages an old audit), else the lead's
    score with the old-audit penalty."""
    if lead.pain_score is not None:
        return lead.pain_score
    return (lead.score or 0.0) - (OLD_AUDIT_PENALTY if audit_is_recent(lead) is False else 0)


def _pain_band(lead: Lead) -> int:
    """Pain in `config.NEAR_TIE_POINTS` bands (higher = more), 0 without a pain
    score (so a file or a test without one orders exactly as before)."""
    if lead.pain_score is None:
        return 0
    width = config.NEAR_TIE_POINTS
    return int(lead.pain_score // width) + 1 if width > 0 else int(lead.pain_score) + 1


def kind_pain(leads: list[Lead], target: int = GIFT_TARGET) -> dict[str, int]:
    """Each signal type's pain at one level (2026-11-03): the sum of its
    `target` most painful leads over `target` (a kind that can fill the gift
    beats one painful lead alone), in `config.NEAR_TIE_POINTS` bands. Empty
    when no lead carries a pain score, so the old order holds."""
    by: dict[str, list[float]] = {}
    for ld in leads:
        if ld.pain_score is not None:
            by.setdefault(ld.signal_type or "", []).append(ld.pain_score)
    width = config.NEAR_TIE_POINTS or 1
    return {t: int(sum(sorted(v, reverse=True)[:target]) / target // width) + 1
            for t, v in by.items()}


def strongest_first(gift: Gift) -> None:
    """List the gift's strongest lead first (2026-10-25): this year's findings,
    then by `strength`. In place; the walk's level order already decided WHICH
    leads are in the gift, this only decides the order they are read in."""
    gift.leads.sort(key=lambda ld: (0 if _recent_finding(ld) else 1, -strength(ld)))


def _home_band(lead: Lead) -> int:
    """The band the own-state level sorts by: bands below `CITY_YIELDS_FROM`
    are one group, so only a lead at or past it gives way to a stronger one
    outside the city."""
    band = strength_band(lead)
    return band if band >= CITY_YIELDS_FROM else STRONG


def _in_city(lead: Lead, home: tuple[str | None, str | None]) -> bool:
    city, state = home
    return bool(city and state and lead.city and lead.state) and \
        norm_state(lead.state) == norm_state(state) and norm_loc(lead.city) == norm_loc(city)


def rotation(lead: Lead, salt: str | None) -> int:
    """A stable per-prospect shuffle among EQUALLY strong record leads
    (2026-10-30): with no allocation limit, firms in one city all got the same
    three organizations (64% of simulated gifts matched another firm's). Seeded
    by the prospect's firm name, so a re-run gives the same gift. Only orders
    leads `sort_key` ties on everything down to their score band
    (`config.NEAR_TIE_POINTS`); 0 for a job-post lead, whose recency is part
    of its claim."""
    if not salt or lead.signal_type not in MAGNET_SIGNALS:
        return 0
    key = f"{salt}|{lead.allocation_key or lead.id}".encode()
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")


def _near_tie_band(lead: Lead) -> float:
    """The lead's strength, coarsened to `config.NEAR_TIE_POINTS` bands for a
    record lead (a job post keeps its exact value: it has no score)."""
    width = config.NEAR_TIE_POINTS
    s = strength(lead)
    if width <= 0 or lead.signal_type not in MAGNET_SIGNALS:
        return s
    return float(int(s // width))


def _unfindable(lead: Lead) -> int:
    return 0 if lead.is_findable else 1


def _flagged(lead: Lead) -> int:
    return 1 if (lead.name_cut_off or lead.name_glued) else 0


def sort_key(lead: Lead, rank: dict[str, int] | None = None,
             focus: str | None = None,
             home: tuple[str | None, str | None] | None = None,
             salt: str | None = None,
             kinds: dict[str, int] | None = None) -> tuple:
    """Within-level re-sort (the level itself is never re-ordered: industry +
    area always take precedence). Strongest signal per the active pack's
    `signal_rank`, then -- when the firm plainly does ONE kind of work -- a
    lead whose service tags suit it, then the magnets' strength order
    (`TYPE_ORDER`), then a resolvable company, then the lead's own score,
    then freshest, then high-confidence date before low.

    The identifier never appears in a sent email, so this is not about the
    link — it is about FINDABILITY. A lead the recipient cannot look up is the
    one most likely to read as invented, so it ranks below every lead they can.

    `is_findable`, not `domain`. A domain is one way to be findable; a
    government identifier with a public filing behind it is a stronger one —
    anyone can register a domain, but only a real filing entity has an EIN with
    a 990 behind it or a CRD with a Form ADV. Ranking on domain alone pushed
    every nonprofit and fund lead to the bottom as "unfindable" when each
    carries a verifiable federal record. Ranked below, never dropped.

    `home` (the prospect's city and state) is passed for the own-state level
    when `STRENGTH_BEATS_CITY`: the strength band, then their city before the
    rest of their state. Without it both are 0 for every lead.

    `salt` (the prospect's firm) rotates record leads whose scores share a
    `config.NEAR_TIE_POINTS` band (`rotation`); the exact score, then the
    document date, break what is left.

    Pain (2026-11-03): inside a strength band (STRONG / MEDIUM / WEAK, never
    across one) the KIND in most pain at this level comes first (`kinds`,
    from `kind_pain`: its three most painful organizations), then the type
    order breaks ties; within a type the lead's pain score is the strength
    (`strength`), so the near-tie rotation works on pain bands exactly as it
    did on score bands. Choosing the kind first keeps a gift filling from one
    kind (one record opener): ranking single leads by pain across kinds cut
    single-kind gifts from 47 to 6 of 100 simulated prospects. Without pain
    scores (`kinds` empty / None) the old order exactly."""
    rank = rank if rank is not None else SIGNAL_RANK
    return (
        rank.get(lead.signal_type, 9),
        # Own-state level only (else 0, 0): the band, then their city first.
        # Before focus, so focus never moves a lead across that line.
        _home_band(lead) if home else 0,
        0 if home is None or _in_city(lead, home) else 1,
        # No focus -> 0 for everyone, so no preference at all.
        0 if focus is None or suits_focus(lead, focus) else 1,
        # The strength band (TYPE_ORDER is monotone in it, so on its own this
        # changes nothing), then the kind in most pain at this level before
        # the type order (0 without pain scores): pain never crosses a band.
        strength_band(lead),
        -(kinds or {}).get(lead.signal_type or "", 0),
        TYPE_ORDER.get(lead.signal_type or "", _OTHER_TYPE),
        _unfindable(lead),
        # A name the source cut off or glued together reaches the email only
        # when nothing else can fill the place: the review flags it either way.
        _flagged(lead),
        # This year's audit findings before every other charity lead (the
        # user, 2026-10-25). Below them, old findings and late filings compete
        # on score with the old-audit penalty, so a weak late filing never jumps
        # a strong old finding. Every non-charity lead ties here.
        0 if _recent_finding(lead) or lead.signal_type != "nonprofit_grant_no_finance_officer"
        else 1,
        # The magnet's own score, where it serves one. Every lead from a single
        # magnet shares one signal_type, so without this the first tiebreak
        # that does any work is RECENCY — which ordered 29,000 nonprofits by
        # fiscal-year end and buried the 160 whose auditor filed a repeat
        # material-weakness finding, the strongest evidence in the inventory.
        # Job-post leads carry no score and are unaffected.
        # An audit filed over a year ago scores OLD_AUDIT_PENALTY less.
        # With a salt, scores within `config.NEAR_TIE_POINTS` of each other
        # (one band) are one strength, ordered by the firm's rotation; the
        # exact score only breaks what that leaves. Type and level come first,
        # so this never reorders across them.
        -_near_tie_band(lead) if salt else 0,
        rotation(lead, salt),
        -strength(lead),
        -_recency(lead),
        0 if lead.effective_date_confidence == "high" else 1,
    )


def compute_match_level(lead: Lead, prospect: Prospect) -> int | None:
    """How closely `lead` matches `prospect`. Niched: 1 niche+city, 2
    niche+state, 3 niche, 4 city, 5 state. Generalist: 1 city, 2 state.
    None = no match (should not be in a gift)."""
    niche_match = False
    if prospect.match_param:
        kind, val = prospect.match_param
        if kind == "niche":
            niche_match = lead.niche == val
        elif kind == "industry":
            niche_match = lead.industry == val
    state_match = bool(
        lead.state and prospect.state and norm_state(lead.state) == norm_state(prospect.state)
    )
    # Same city NAME is not the same city: "arlington" WA is not "arlington"
    # TX. A city match needs the state to match as well.
    city_match = state_match and bool(
        lead.city and prospect.city and norm_loc(lead.city) == norm_loc(prospect.city)
    )
    if prospect.classification == "niched":
        if niche_match and city_match:
            return 1
        if niche_match and state_match:
            return 2
        if niche_match:
            return 3
        if city_match:
            return 4
        if state_match:
            return 5
        return None
    if city_match:
        return 1
    if state_match:
        return 2
    return None


def _levels_for(p: Prospect, *, niche_only: bool = False) -> list[tuple[int, dict[str, Any]]]:
    """The match levels, nearest first. With `STRENGTH_BEATS_CITY` the city
    levels (1 and 4; a generalist's 1) are folded into their state level, which
    `_walk` sorts by band and then city first (`sort_key(home=...)`)."""
    levels: list[tuple[int, dict[str, Any]]] = []
    city_levels = bool(p.city and p.state) and not STRENGTH_BEATS_CITY
    if p.classification == "niched" and p.match_param:
        kind, val = p.match_param
        base = {kind: val}
        # A city level always carries the state (see compute_match_level), so
        # a prospect with no state gets no city level.
        if city_levels:
            levels.append((1, {**base, "city": p.city, "state": p.state}))
        if p.state:
            levels.append((2, {**base, "state": p.state}))
        levels.append((3, dict(base)))
        # niche_only (Change 2 / Gate B): stop at L3 so the gift is entirely
        # on-niche leads. Dropping the L4/L5 geo fallback means the gift is
        # either all_niche or empty — never padded with off-niche leads.
        if niche_only:
            return levels
        if city_levels:
            levels.append((4, {"city": p.city, "state": p.state}))
        if p.state:
            levels.append((5, {"state": p.state}))
    else:
        if city_levels:
            levels.append((1, {"city": p.city, "state": p.state}))
        if p.state:
            levels.append((2, {"state": p.state}))
    return levels


def _far_levels(p: Prospect) -> list[tuple[int, dict[str, Any]]]:
    """Past the prospect's own state: the bordering states, then anywhere.
    Only for a prospect in a US state (a firm in Ontario gets none)."""
    home = norm_state(p.state)
    if not FAR_LEVELS or home not in ADJACENT_STATES:
        return []
    near = sorted(ADJACENT_STATES[home])
    return ([(LEVEL_NEARBY, {"states": near})] if near else []) + [(LEVEL_NATIONWIDE, {})]


def _find_priority_lead(
    prospect: Prospect, scraper: _Scraper, excluded: set[str], *,
    pack: NichePack, niche_only: bool = False,
    signal_types: frozenset[str] | None = None,
) -> Lead | None:
    """3a: the pack's priority signal (CFO: cfo_wanted) via match_param, then
    city, then state (fresh). First query with a hit wins; its best (re-sorted)
    lead is returned. Packs with no priority signal (e.g. trucking) short-circuit."""
    if not pack.priority_signal:
        return None
    if signal_types is not None and pack.priority_signal not in signal_types:
        return None
    queries: list[dict[str, Any]] = []
    if prospect.classification == "niched" and prospect.match_param:
        kind, val = prospect.match_param
        queries.append({kind: val})
    # niche_only: don't fall back to a geo priority lead — it would be off-niche.
    if not niche_only:
        if prospect.city and prospect.state:
            queries.append({"city": prospect.city, "state": prospect.state})
        if prospect.state:
            queries.append({"state": prospect.state})
    for kwargs in queries:
        leads = [
            lead for lead in scraper.leads(
                signal_type=pack.priority_signal, freshness="fresh",
                exclude_ids=list(excluded), **kwargs,
            )
            if lead.id not in excluded and not _off_limits(lead, prospect)
            and giftable(lead, pack.signal_rank)
            and not _same_company(lead, prospect.used_leads)
        ]
        if leads:
            leads.sort(key=lambda lead: sort_key(lead, pack.signal_rank, prospect.focus,
                                                 salt=prospect.firm_name))
            return leads[0]
    return None


def _name_key(name: str | None) -> str:
    """A company name reduced for comparison: lowercase, punctuation dropped,
    legal suffixes removed. "Habitat For Humanity International, Inc." and
    "HABITAT FOR HUMANITY INTERNATIONAL INC" are the same words on the page."""
    text = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    text = re.sub(r"\b(inc|incorporated|llc|l l c|ltd|corp|corporation|co|"
                  r"company|the|of|and)\b", " ", text)
    return " ".join(text.split())


def _same_company(lead: Lead, gift: list[Lead]) -> bool:
    """True when this lead is a company already in the gift.

    Matched on IDENTITY, not name: the same company reaches the store under
    several names (a slug-derived one, a legal one, a hashed one) and dedup
    upstream keys on the name, so name comparison misses exactly the duplicates
    that survive. Listing one company twice makes a gift of three read as a
    gift of two and reads as careless.

    Identity is `entity_id` — an EIN, a CRD, or a domain — rather than the
    domain alone. Most nonprofit and fund leads have no useful website (and a
    few carry a LinkedIn URL in the domain field), so domain-only matching
    silently deduped nothing across two of the three magnets.

    The NAME is then checked as well, and that is not redundant. 116 separate
    charities are called "Habitat For Humanity International Inc" — different
    cities, different EINs, genuinely different organizations. Identity-only
    matching lets two of them into one gift, where the reader sees the same
    name twice and concludes the list is broken. They are right to: a gift of
    three that names two things identically reads as two, however defensible
    the underlying data is."""
    ident = lead.identity
    if ident and any(other.identity == ident for other in gift):
        return True
    name = _name_key(lead.company)
    return bool(name) and any(_names_collide(name, _name_key(o.company)) for o in gift)


def _names_collide(a: str, b: str) -> bool:
    """The same name on the page, or one name the other plus a tail ("Have A
    Heart" / "Have A Heart CC": two WA cannabis UBIs of one trade name, which
    a reader takes for one business listed twice, 2026-10-30). The shorter
    must have two or more words, so "Acme" never swallows "Acme Roofing"."""
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a.split(), b.split()), key=len)
    return len(short) >= 2 and long_[:len(short)] == short


# Words a CPA firm's name carries that do not identify it. "Denman & Company,
# LLP" on a filing and "Denman & Co CPAs" on a website are the same firm.
_FIRM_NOISE = re.compile(
    r"\b(llp|llc|l l c|pllc|pc|p c|psc|pa|p a|ltd|inc|co|company|cpa|cpas|"
    r"certified|public|accountants?|accounting|associates|group|partners|"
    r"professional|corporation|corp|firm|and|the|of)\b")


def _firm_key(name: str | None) -> frozenset[str]:
    text = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    return frozenset(_FIRM_NOISE.sub(" ", text).split())


def _audited_by(lead: Lead, prospect: Prospect) -> bool:
    """True when the prospect firm is this lead's own auditor.

    A nonprofit lead carries the CPA firm that signed its Single Audit
    (`fac_auditor_firm`). Handing that firm its own audit client as a "lead"
    is the one gift that proves we did not look -- they wrote the finding.
    Matched on the name's distinguishing words; a false match only costs a
    swap from a deep inventory, a missed one costs the prospect."""
    auditor = None
    for sig in lead.signals:
        p = getattr(sig, "payload", None) or {}
        # The firm that signed this lead's audit, whichever record names it:
        # a Single Audit (FAC), a plan audit (Form 5500), a broker-dealer's
        # annual audit (X-17A-5), a local government's FAC audit.
        auditor = (p.get("fac_auditor_firm") or p.get("auditor_firm")
                   or p.get("current_auditor") or p.get("current_provider"))
        if auditor:
            break
    a, f = _firm_key(auditor), _firm_key(prospect.firm_name)
    if not a or not f:
        return False
    return a == f or (min(len(a), len(f)) >= 2 and (a <= f or f <= a))


LICENSE_SIGNALS: frozenset[str] = frozenset({
    "construction_new_licensed_business",
    "construction_license_upgrade",
})

# Records one STATE issued, whatever address the lead prints (2026-10-27): a
# Washington public-works filing by a Saint Paul contractor, a Nevada license
# held by a California crane company, a California tax-credit project owned
# from New York. Like a license, true and beside the point for a firm in
# another state (`_licensed_elsewhere`). The issuer is fixed by the program;
# None means "read the record's own state" (`licensing_state`).
ISSUED_BY: dict[str, str | None] = {
    "construction_first_prevailing_wage_intent": "WA",
    "construction_nv_license_limit": "NV",
    "construction_fl_stop_work_order": "FL",
    "top_tax_delinquent": "CA",
    "tcac_placed_in_service": "CA",
    "ca_dre_trust_fund_discipline": "CA",
    "ca_dre_audit_discipline": "CA",
    "nc_rec_trust_account_discipline": "NC",
    "fl_condo_new_association": "FL",
    "ny_omig_final_audit": "NY",
    "wi_choice_school_new": "WI",
    "charter_audit_missing": "FL",
    "water_ca_annual_report_missing": "CA",
    "nv_casino_new_nonrestricted_license": "NV",
    "film_ca_credit_allocated": "CA",
    "film_nj_credit_approved": "NJ",
    "ae_txdot_overhead_approval_lapsed": "TX",
    "ae_caltrans_first_icr_acceptance": "CA",
}


def licensing_state(lead: Lead) -> str | None:
    """The state that issued a license (WA L&I, Florida DBPR), read off the
    record's own lookup / source link, else its payload `state`."""
    p: dict = {}
    for sig in lead.signals:
        data = getattr(sig, "payload", None)
        if isinstance(data, dict) and data:
            p = data
            break
    where = " ".join(str(x or "") for x in (p.get("lookup"), p.get("dataset"),
                                             lead.primary_source_url))
    if "lni.wa.gov" in where or "data.wa.gov" in where:
        return "WA"
    if "myfloridalicense" in where:
        return "FL"
    return p.get("state") or None


def _licensed_elsewhere(lead: Lead, prospect: Prospect) -> bool:
    """A license lead from a state other than the prospect's own. The lead is
    matched by its ADDRESS, so a Clovis, CA roofer with a new Florida license
    reached a California firm as "newly licensed in florida" (2026-10-25): true,
    and beside the point for them. Unknown on either side is not "elsewhere"."""
    if lead.signal_type in ISSUED_BY:
        issuer = ISSUED_BY[lead.signal_type] or licensing_state(lead)
        return bool(issuer and prospect.state) and \
            norm_state(issuer) != norm_state(prospect.state)
    if lead.signal_type not in LICENSE_SIGNALS:
        return False
    issuer = licensing_state(lead)
    return bool(issuer and prospect.state) and norm_state(issuer) != norm_state(prospect.state)


def _off_limits(lead: Lead, prospect: Prospect) -> bool:
    """A lead this prospect must never see: its own audit client, an
    organization this firm was already handed (or, with
    `config.EXCLUSIVE_PER_REGION`, one handed to another firm in its region:
    `gift.allocation`), or a license another state issued."""
    key = lead.allocation_key
    return _audited_by(lead, prospect) or _licensed_elsewhere(lead, prospect) or (
        key is not None and key in prospect.blocked_identities)


def _pick_leads(
    prospect: Prospect, scraper: _Scraper, excluded: set[str], *, target: int,
    into: list[Lead], rank: dict[str, int], niche_only: bool = False,
    signal_types: frozenset[str] | None = None, nationwide: bool = False,
) -> None:
    """The Level walk. Mutates `into` / `excluded` in place.

    The match levels (`_levels_for`), then -- outside a `niche_only` build --
    the far levels (`_far_levels`: strong leads from the bordering states, then
    from anywhere). Row 8 (new businesses) never joins that walk. With
    `ROW8_IN_GIFTS` it may fill what is left, last, and only from the
    prospect's OWN STATE (its city, then its state), never at a niche level
    and never in a `niche_only` build: a new business is a registry filing
    with a NAICS code, too thin to claim a vertical on (the second review run
    passed a psychiatry practice and a notary as "law firms"), and a
    Connecticut filing means nothing to a Seattle firm.

    Measured 2026-10-30 over the 1,107 unsent prospects (Gate B's model call
    stubbed): every US prospect's gift reached 3 leads inside its own state;
    the far levels are the fallback for a thinner inventory (the original five
    magnets alone: they replace the 42% of gifts Row 8 filled while the
    one-organization-per-state rule was on).

    `signal_types` keeps only leads of those kinds (email 2 follows email 1's
    kind), and `nationwide` adds a last level with no place at all for a
    prospect the far levels do not cover (no US state); a niched one already
    has its niche-only level 3."""
    levels = _levels_for(prospect, niche_only=niche_only)
    far = [] if niche_only else _far_levels(prospect)
    levels += far
    if nationwide and not far and not (prospect.classification == "niched"
                                       and prospect.match_param):
        levels.append((LEVEL_NATIONWIDE, {}))
    _walk(prospect, scraper, excluded, levels, target=target, into=into, rank=rank,
          backup=False, signal_types=signal_types)
    if niche_only or not prospect.state or not ROW8_IN_GIFTS:
        return
    own_state = [(lvl, kw) for lvl, kw in levels
                 if "state" in kw and set(kw) <= {"city", "state"}]
    _walk(prospect, scraper, excluded, own_state, target=target, into=into, rank=rank,
          backup=True, signal_types=signal_types)


def _query(scraper: _Scraper, kwargs: dict[str, Any], **common: Any) -> list[Lead]:
    """One level's leads: a `states` level asks once per state."""
    if "states" not in kwargs:
        return scraper.leads(**common, **kwargs)
    rest = {k: v for k, v in kwargs.items() if k != "states"}
    return [ld for st in kwargs["states"] for ld in scraper.leads(**common, state=st, **rest)]


def _walk(
    prospect: Prospect, scraper: _Scraper, excluded: set[str],
    levels: list[tuple[int, dict[str, Any]]], *, target: int, into: list[Lead],
    rank: dict[str, int], backup: bool,
    signal_types: frozenset[str] | None = None,
) -> None:
    # The own-state level ranks by strength band, then their city first.
    home = (prospect.city, prospect.state) if STRENGTH_BEATS_CITY else None
    for freshness in ("fresh", "stale"):
        if len(into) >= target:
            return
        for level, kwargs in levels:
            if len(into) >= target:
                return
            far = level >= LEVEL_NEARBY
            leads = [
                lead for lead in _query(scraper, kwargs, freshness=freshness,
                                        exclude_ids=list(excluded))
                # Not added to `excluded`: the lead is fine for every other
                # prospect, only not for this one.
                if lead.id not in excluded and not _off_limits(lead, prospect)
                and is_backup(lead) == backup
                and (signal_types is None or lead.signal_type in signal_types)
                and not (far and signal_types is None and strength_band(lead) != STRONG)
                and giftable(lead, rank)
            ]
            own_state = home is not None and "state" in kwargs and "city" not in kwargs
            kinds = kind_pain(leads)
            leads.sort(key=lambda lead: sort_key(lead, rank, prospect.focus,
                                                 home if own_state else None,
                                                 salt=prospect.firm_name, kinds=kinds))
            for lead in leads:
                if len(into) >= target:
                    break
                if _same_company(lead, into) or _same_company(lead, prospect.used_leads):
                    # Skip, but do NOT mark excluded: `excluded` is the sent /
                    # already-used ledger, and this lead was never used. It stays
                    # available for the next prospect's gift. `used_leads` is
                    # the rest of this firm's sequence (email 1 when building
                    # email 2): one organization never appears twice in it,
                    # under another record or the same name (2026-10-30: 21 of
                    # 1,076 simulated sequences repeated one).
                    log.debug("gift: skipping %s — %s already in this gift",
                              lead.company, lead.domain)
                    continue
                into.append(lead)
                excluded.add(lead.id)


def build_gift(
    prospect: Prospect, scraper: _Scraper, *, target: int = GIFT_TARGET,
    niche_only: bool = False, pack: NichePack | None = None,
    signal_types: frozenset[str] | None = None, nationwide: bool = False,
) -> Gift | None:
    """Build the gift. `niche_only` (Change 2 / Gate B) restricts to on-niche
    leads (levels 1-3): the returned gift is all_niche or None, never padded
    with geo leads — so the tiering resolver can test a candidate niche.

    `pack` supplies the niche's priority signal and WHAT categorization;
    defaults to the CFO pack so existing callers are unchanged. `signal_types`
    and `nationwide` narrow and widen the walk (see `_pick_leads`)."""
    pack = pack or default_pack()
    rank = dict(pack.signal_rank)
    gift: list[Lead] = []
    excluded: set[str] = set(prospect.sent_lead_ids)

    lead = _find_priority_lead(prospect, scraper, excluded, pack=pack, niche_only=niche_only,
                               signal_types=signal_types)
    if lead is not None:
        gift.append(lead)
        excluded.add(lead.id)

    _pick_leads(prospect, scraper, excluded, target=target, into=gift, rank=rank,
                niche_only=niche_only, signal_types=signal_types, nationwide=nationwide)

    if not gift:
        return None

    best = _best_lead(gift, prospect, rank)
    all_niche, geo = _honesty(gift, prospect)
    has_priority = bool(pack.priority_signal) and any(
        lead.signal_type == pack.priority_signal for lead in gift
    )
    shape = "singular" if (len(gift) == 1 or has_priority) else "plural"
    return Gift(
        leads=gift,
        best_lead=best,
        gift_size=len(gift),
        all_niche=all_niche,
        geo_level=geo,
        subject_shape=shape,
        what_category=pack.what_category(gift),
        best_lead_level=compute_match_level(best, prospect),
    )


def pull_one_lead(
    prospect: Prospect, scraper: _Scraper, *, pack: NichePack | None = None
) -> Lead | None:
    """Follow-up pull (Steps 6/7): ONE new lead, same levels, exclude_ids
    already sent. The priority signal (3a) still leads. Copy layer decides
    value/fallback; this returns the lead."""
    gift = build_gift(prospect, scraper, target=1, pack=pack)
    return gift.leads[0] if gift else None


def _best_lead(gift: list[Lead], prospect: Prospect, rank: dict[str, int] | None = None) -> Lead:
    rank = rank if rank is not None else SIGNAL_RANK
    def key(lead: Lead) -> tuple:
        return (
            rank.get(lead.signal_type, 9),
            # The same strength order the gift was built in, so the subject
            # speaks for its strongest lead (a charity audit finding before a
            # new license, never a Row 8 fill before either).
            # Pain inside a band first (2026-11-03; 0 without pain scores).
            strength_band(lead),
            -_pain_band(lead),
            TYPE_ORDER.get(lead.signal_type or "", _OTHER_TYPE),
            # A domainless lead is the likeliest to read as invented, so it
            # must not be the one the subject line is built from.
            0 if lead.domain else 1,
            -strength(lead) if lead.pain_score is not None else -(lead.score or 0.0),
            0 if lead.freshness == "fresh" else 1,
            compute_match_level(lead, prospect) or 99,
        )
    return min(gift, key=key)


def _honesty(gift: list[Lead], prospect: Prospect) -> tuple[bool, str]:
    if prospect.classification == "niched":
        # A Row 8 lead never backs a niche claim, whatever its NAICS tag says.
        all_niche = all((compute_match_level(lead, prospect) or 99) <= 3
                        and not is_backup(lead) for lead in gift)
    else:
        all_niche = False

    def state_ok(lead: Lead) -> bool:
        return bool(
            lead.state and prospect.state and norm_state(lead.state) == norm_state(prospect.state)
        )

    def city_ok(lead: Lead) -> bool:
        return state_ok(lead) and bool(
            lead.city and prospect.city and norm_loc(lead.city) == norm_loc(prospect.city))

    if all(city_ok(lead) for lead in gift):
        geo = "city"
    elif all(state_ok(lead) for lead in gift):
        geo = "state"
    else:
        geo = "none"
    return all_niche, geo


# The vertical magnets. A lead from one of these is NOT hiring and did NOT
# raise — the whole point is that it emitted no announcement at all. Named here
# rather than imported from copy.email to keep the engine free of a copy
# dependency; `test_magnets` pins the two lists together.
# The magnets that verify an ABSENCE (no finance officer, no administrator,
# nobody in finance).
ABSENCE_SIGNALS: frozenset[str] = frozenset({
    "nonprofit_grant_no_finance_officer",
    "adv_no_fund_administrator",
    "ecommerce_sku_load_no_finance_staff",
})
# The lead inventory's record-based signals: an EVENT on a public record (an
# award, a license, a contract, a grant, a formation). Not hiring, not a raise.
RECORD_SIGNALS: frozenset[str] = frozenset({
    "construction_federal_award_davis_bacon",
    "construction_new_licensed_business",
    "construction_license_upgrade",
    "federal_cost_reimbursement_contract",
    "federal_first_time_grant",
    "new_business_formed",
}) | (frozenset(_TYPE_STRENGTH) - ABSENCE_SIGNALS - HELD_TYPES)  # + duty
MAGNET_SIGNALS: frozenset[str] = ABSENCE_SIGNALS | RECORD_SIGNALS

# signal type -> subject WHAT category. Each names only what its own filter
# actually verified.
_MAGNET_WHAT: dict[str, str] = {
    # A charity is keyed by what its audit shows (`what_key`), never by the
    # removed Row 4 claim "no finance officer on the 990".
    "nonprofit_audit_finding": "nonprofit_audit",
    "nonprofit_record": "public_record",
    "adv_no_fund_administrator": "unstaffed_funds",
    "ecommerce_sku_load_no_finance_staff": "unstaffed_ecommerce",
    "construction_federal_award_davis_bacon": "davis_bacon",
    "construction_new_licensed_business": "new_license",
    "construction_license_upgrade": "license_upgrade",
    "federal_cost_reimbursement_contract": "auditable_contract",
    "federal_first_time_grant": "first_grant",
    "new_business_formed": "new_business",
}
# Each legal-duty type is its own category, named by its signal type
# (`copy.subject.RECORD_PLURAL_WHAT` carries their words).
_MAGNET_WHAT.update({t: t for t in RECORD_SIGNALS if t not in _MAGNET_WHAT})


# What a charity's federal audit shows (`nonprofit_phrase` reads the same
# fields): an auditor's finding on its financial controls or on how it handles
# grant money.
_NONPROFIT_FINDINGS = ("fac_material_weakness", "fac_significant_deficiency",
                       "fac_program_control_finding", "fac_material_noncompliance")


def what_key(lead: Lead) -> str:
    """The key a subject / DM WHAT is looked up by: the signal type, except a
    nonprofit, which is keyed by what its audit shows -- `nonprofit_audit_finding`
    when an auditor flagged its controls or its grant handling, else
    `nonprofit_record` (a late or missing audit: neutral wording).

    The old subject, "with no finance officer, from their 990s", was the claim
    of Row 4, removed at the source on 2026-10-15; Row 1 qualifies a charity
    on its audit, and 3 of 24 charities under that subject listed an officer."""
    if lead.signal_type == "nonprofit_grant_no_finance_officer":
        for sig in lead.signals:
            p = getattr(sig, "payload", None) or {}
            if any(p.get(k) for k in _NONPROFIT_FINDINGS):
                return "nonprofit_audit_finding"
        return "nonprofit_record"
    return lead.signal_type or ""


def _cfo_what_category(gift: list[Lead]) -> str:
    """CFO subject WHAT category: raised | hiring | unstaffed[_magnet] | a
    record-signal category (davis_bacon, new_license, ...) | public_record |
    mixed.

    `unstaffed` exists because the previous logic was a two-way split — a lead
    either raised or, by elimination, was "hiring". That inverted the truth for
    a magnet lead: a nonprofit whose 990 lists no finance officer is precisely
    a company that has NOT posted a role, and a subject line saying it is
    "hiring finance leadership right now" is a false claim about a named
    organization in the first line the recipient reads."""
    def raised(lead: Lead) -> bool:
        return lead.signal_type in FUNDING_SIGNALS

    def unstaffed(lead: Lead) -> bool:
        return lead.signal_type in MAGNET_SIGNALS

    def hiring(lead: Lead) -> bool:
        return lead.signal_type not in FUNDING_SIGNALS and not unstaffed(lead)

    if all(raised(lead) for lead in gift):
        return "raised"
    if all(unstaffed(lead) for lead in gift):
        # Per MAGNET, not one shared word: the three do not verify the same
        # thing. Nonprofit and Ecommerce both confirm no finance staff; Funds
        # confirms no outside ADMINISTRATOR and says nothing about who works
        # there, so it must not borrow their phrasing.
        kinds = {what_key(lead) for lead in gift}
        if len(kinds) == 1:
            return _MAGNET_WHAT[next(iter(kinds))]
        if kinds <= ABSENCE_SIGNALS:
            return "unstaffed"
        # A gift mixing an event (an award, a formation) with anything else:
        # "with nobody running finance" is false of a new license, so the
        # subject says only that public records show a need.
        return "public_record"
    if all(hiring(lead) for lead in gift):
        return "hiring"
    return "mixed"
