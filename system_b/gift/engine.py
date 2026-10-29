"""Step 3 — build the gift (pure logic).

3a fractional-CFO check, 3b two-round Level 1-5 walk, 3c count, 3d best
lead, 3e honesty values. Geography-first: gift is assembled by match
level; signal type then date are tiebreaks WITHIN a level (except 3a).

Order (2026-10-18, the user's rules): the match level always decides first
(industry + area; the walk itself is unchanged, and so are Gates A and B).
Within a level `sort_key`: the pack's `signal_rank` -> a lead suiting the
firm's CLEAR focus (`Prospect.focus`, only when its site is plainly one kind of
work) -> `TYPE_ORDER` across the magnets -> findable -> the lead's score
(within a type) -> newest -> date confidence. Row 8 (new businesses) is a
backup: `_pick_leads` walks every other type first and lets Row 8 fill only
the places left. `_best_lead`: rank -> TYPE_ORDER -> domain -> score ->
freshness -> match level.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Protocol

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
    "ca_dre_audit_discipline", "union_funds_shortage",
    # 2. the original strong pair
    "construction_federal_award_davis_bacon",       # federal construction award
    "federal_cost_reimbursement_contract",          # cost-type federal contract
    # 3. a duty just switched on
    "plan_audit_first_due", "welfare_plan_audit_threshold", "medicare_new_part_a_provider",
    "snf_change_of_ownership", "hospital_change_of_ownership", "hrsa_new_health_center",
    "cu_over_500m_no_fs_audit", "cu_stale_audit", "wi_choice_school_new",
    "construction_first_prevailing_wage_intent", "hud_new_owner",
    "ttb_new_distillery_permit", "ttb_new_winery_permit",
    "nv_casino_new_nonrestricted_license", "film_ca_credit_allocated",
    "film_nj_credit_approved", "ae_caltrans_first_icr_acceptance",
    "fl_condo_new_association", "plan_audit_first_filed",
    # 4. a required report late or missing (a charity two years without a 990
    # first: one more year and its exemption is revoked by law)
    "nonprofit_990_missed_2yr", "nonprofit_single_audit_late", "nonprofit_990_missed_1yr", "local_gov_single_audit_late", "late_filing_notice",
    "nasdaq_late_filing_deficiency", "rega_tier2_1k_missing", "bd_annual_audit_late",
    "charter_audit_missing", "water_ca_annual_report_missing", "union_lm_report_late",
    "local_gov_financial_report_late", "ae_txdot_overhead_approval_lapsed",
    "proprietary_90_10_near_limit", "auditor_change", "cu_approaching_fs_audit",
    # 5. tax debts and self-reported plan or 990 problems
    "federal_tax_lien", "state_tax_lien", "unemployment_tax_lien", "top_tax_delinquent",
    "construction_fl_stop_work_order", "pension_unpaid_min_contribution",
    "plan_prohibited_transaction", "nonprofit_ubi_no_990t", "nonprofit_excess_benefit",
    "nonprofit_exemption_revoked", "nonprofit_state_audit_line_no_audit",
    "plan_late_contributions", "plan_termination_pending",
    # 6. the original weaker rows
    "federal_first_time_grant", "govcon_first_sbir_phase2", "tcac_placed_in_service",
    "construction_license_upgrade", "construction_nv_license_limit",
    "construction_new_licensed_business",
)
TYPE_ORDER: dict[str, int] = {t: i for i, t in enumerate(_TYPE_STRENGTH)}

# HELD (2026-10-29): types whose wording is written (`copy.duty.HELD_DUTIES`)
# but not yet approved by the user. They keep their rank above, but are no
# record signal: no gift, opener, subject or DM uses one. The inventory holds
# them back too (its `sources.APPROVED_SIGNALS` leaves them out, so `publish`
# never sends one). To approve a type: delete it here AND add it to the
# inventory's APPROVED_SIGNALS (`test_duty_copy` checks the two agree).
# OUTREACH_PREVIEW_HELD=1 lifts the hold for a local preview run only.
HELD_TYPES: frozenset[str] = frozenset() if os.environ.get("OUTREACH_PREVIEW_HELD") else \
    frozenset({"nonprofit_990_missed_1yr", "nonprofit_990_missed_2yr"})
_OTHER_TYPE = len(_TYPE_STRENGTH)
TYPE_ORDER.update({"new_business_formed": _OTHER_TYPE + 1,
                   "new_business_expanding": _OTHER_TYPE + 2})

# Row 8 is a BACKUP: a gift is built from every other lead type first, and a
# new business only fills a place nothing else could (see `_pick_leads`).
BACKUP_PREFIX = "new_business_"


def is_backup(lead: Lead) -> bool:
    return (lead.signal_type or "").startswith(BACKUP_PREFIX)


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
    """The lead's score with the old-audit penalty: the order the walk uses
    within a type, and the order an email lists its leads in."""
    return (lead.score or 0.0) - (OLD_AUDIT_PENALTY if audit_is_recent(lead) is False else 0)


def strongest_first(gift: Gift) -> None:
    """List the gift's strongest lead first (2026-10-25): this year's findings,
    then by `strength`. In place; the walk's level order already decided WHICH
    leads are in the gift, this only decides the order they are read in."""
    gift.leads.sort(key=lambda ld: (0 if _recent_finding(ld) else 1, -strength(ld)))


def sort_key(lead: Lead, rank: dict[str, int] | None = None,
             focus: str | None = None) -> tuple:
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
    carries a verifiable federal record. Ranked below, never dropped."""
    rank = rank if rank is not None else SIGNAL_RANK
    return (
        rank.get(lead.signal_type, 9),
        # No focus -> 0 for everyone, so no preference at all.
        0 if focus is None or suits_focus(lead, focus) else 1,
        TYPE_ORDER.get(lead.signal_type or "", _OTHER_TYPE),
        0 if lead.is_findable else 1,
        # A name the source cut off or glued together reaches the email only
        # when nothing else can fill the place: the review flags it either way.
        1 if (lead.name_cut_off or lead.name_glued) else 0,
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
    levels: list[tuple[int, dict[str, Any]]] = []
    if p.classification == "niched" and p.match_param:
        kind, val = p.match_param
        base = {kind: val}
        # A city level always carries the state (see compute_match_level), so
        # a prospect with no state gets no city level.
        if p.city and p.state:
            levels.append((1, {**base, "city": p.city, "state": p.state}))
        if p.state:
            levels.append((2, {**base, "state": p.state}))
        levels.append((3, dict(base)))
        # niche_only (Change 2 / Gate B): stop at L3 so the gift is entirely
        # on-niche leads. Dropping the L4/L5 geo fallback means the gift is
        # either all_niche or empty — never padded with off-niche leads.
        if niche_only:
            return levels
        if p.city and p.state:
            levels.append((4, {"city": p.city, "state": p.state}))
        if p.state:
            levels.append((5, {"state": p.state}))
    else:
        if p.city and p.state:
            levels.append((1, {"city": p.city, "state": p.state}))
        if p.state:
            levels.append((2, {"state": p.state}))
    return levels


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
        ]
        if leads:
            leads.sort(key=lambda lead: sort_key(lead, pack.signal_rank, prospect.focus))
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
    return bool(name) and any(_name_key(o.company) == name for o in gift)


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
    organization already handed to another firm in its region, or a license
    another state issued."""
    key = lead.allocation_key
    return _audited_by(lead, prospect) or _licensed_elsewhere(lead, prospect) or (
        key is not None and key in prospect.blocked_identities)


def _pick_leads(
    prospect: Prospect, scraper: _Scraper, excluded: set[str], *, target: int,
    into: list[Lead], rank: dict[str, int], niche_only: bool = False,
    signal_types: frozenset[str] | None = None, nationwide: bool = False,
) -> None:
    """The two-round Level walk. Mutates `into` / `excluded` in place.

    First over every lead type EXCEPT Row 8 (new businesses). Then, only if
    places are left, Row 8 -- and only from the prospect's OWN STATE (its city,
    then its state), never at a niche level and never in a `niche_only` build.
    A new business is a registry filing with a NAICS code, which is too thin
    to claim a vertical on (the second review run passed a psychiatry practice
    and a notary as "law firms"), and a Connecticut filing means nothing to a
    Seattle firm. The same freshness rounds, dedupe and off-limits rules apply.

    `signal_types` keeps only leads of those kinds (email 2 follows email 1's
    kind), and `nationwide` adds a last level with no place at all for a
    prospect matched on geography (a niched one already has its niche-only
    level 3)."""
    levels = _levels_for(prospect, niche_only=niche_only)
    if nationwide and not (prospect.classification == "niched" and prospect.match_param):
        levels.append((6, {}))
    _walk(prospect, scraper, excluded, levels, target=target, into=into, rank=rank,
          backup=False, signal_types=signal_types)
    if niche_only or not prospect.state:
        return
    own_state = [(lvl, kw) for lvl, kw in levels
                 if "state" in kw and set(kw) <= {"city", "state"}]
    _walk(prospect, scraper, excluded, own_state, target=target, into=into, rank=rank,
          backup=True, signal_types=signal_types)


def _walk(
    prospect: Prospect, scraper: _Scraper, excluded: set[str],
    levels: list[tuple[int, dict[str, Any]]], *, target: int, into: list[Lead],
    rank: dict[str, int], backup: bool,
    signal_types: frozenset[str] | None = None,
) -> None:
    for freshness in ("fresh", "stale"):
        if len(into) >= target:
            return
        for _level, kwargs in levels:
            if len(into) >= target:
                return
            leads = [
                lead for lead in scraper.leads(
                    freshness=freshness, exclude_ids=list(excluded), **kwargs,
                )
                # Not added to `excluded`: the lead is fine for every other
                # prospect, only not for this one.
                if lead.id not in excluded and not _off_limits(lead, prospect)
                and is_backup(lead) == backup
                and (signal_types is None or lead.signal_type in signal_types)
            ]
            leads.sort(key=lambda lead: sort_key(lead, rank, prospect.focus))
            for lead in leads:
                if len(into) >= target:
                    break
                if _same_company(lead, into):
                    # Skip, but do NOT mark excluded: `excluded` is the sent /
                    # already-used ledger, and this lead was never used. It stays
                    # available for the next prospect's gift.
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
            TYPE_ORDER.get(lead.signal_type or "", _OTHER_TYPE),
            # A domainless lead is the likeliest to read as invented, so it
            # must not be the one the subject line is built from.
            0 if lead.domain else 1,
            -(lead.score or 0.0),
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
}) | (frozenset(_TYPE_STRENGTH) - {"nonprofit_grant_no_finance_officer"} - HELD_TYPES)  # + duty
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
