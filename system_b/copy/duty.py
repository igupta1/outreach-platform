"""The legal-duty record signals (2026-10-27): one wording entry per approved
signal type from the lead inventory's batches 1-8b (Inventory
`sources.APPROVED_SIGNALS`). ALL deterministic code: no model writes any of it.

Each entry fills the same slots the six original record signals have in
`copy.email` / `copy.subject` / `copy.linkedin`, in the record-opener format
(see CLAUDE.md, "The record opener and the engineer line"):

    these 3 companies in columbus reported late deposits of employee
    contributions on their latest form 5500s:

    1. Acme Tool & Die
    2. Bright Dental Group
    3. Summit Roofing

  plural / singular   the predicate after "these 3 [noun] [in X]" / "this one
                      [in X]"; the singular one is also email 2's sentence
                      ("one more in ohio: Acme reported ...").
  why                 (plural, singular) said after a comma, ONLY where a rule
                      follows from the record itself (a plan past 120 account
                      holders owes its first plan audit, 29 CFR 2520.103-1); a
                      lien, a notice or a discipline order gets none.
  detail              what differs per lead, in parentheses after its name.
  line                the <= 8-word phrase a gift MIXING kinds prints per lead.
  short               the phone-length subject's WHAT (plural, one lead).
  noun                what the leads are (singular, plural); None keeps
                      `lead_noun`'s default ("nonprofits" / "companies").
  org                 the engineer line says "organizations", not "companies".
  bare                the opener prints no business noun at all (Restaurants).

Every claim is the record's own words: "reported ... on its latest form
5500" (a Yes can be carried over a year), "doesn't have ... on edgar yet"
(never "is delinquent"), "were listed by their state as late" (never
"broke the law"). No dollar figure, no date beyond a form's year, no em dash.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from system_b.clients.people import looks_like_person
from system_b.gift.engine import HELD_TYPES
from system_b.models import Lead

Text = str | Callable[[list[Lead]], str]


def _payload(lead: Lead) -> dict:
    for sig in lead.signals:
        data = getattr(sig, "payload", None)
        if isinstance(data, dict) and data:
            return data
    return {}


def _months(days: object) -> str:
    """`7 months` from a day count; "" when there is none."""
    if not isinstance(days, (int, float)) or days < 30:
        return ""
    n = int(days) // 30
    return "a month" if n == 1 else f"{n} months"


def _one(values: list[str]) -> str:
    """The value every lead shares, else ""."""
    vals = {v for v in values if v}
    return next(iter(vals)) if len(vals) == 1 and all(values) else ""


WHY_MAX_WORDS = 10


@dataclass(frozen=True)
class Duty:
    plural: Text
    singular: Callable[[Lead], str] | str
    line: Callable[[Lead], str] | str
    short: tuple[str, str] | Callable[[list[Lead]], tuple[str, str]]
    why: tuple[str, str] | Callable[[list[Lead]], tuple[str, str] | None] | None = None
    detail: Callable[[Lead], str] | None = None
    followup: Callable[[Lead], str] | None = None
    noun: tuple[str, str] | Callable[[Lead], tuple[str, str] | None] | None = None
    org: bool = False
    # `bare`: the record proves a licence, not what the business is, so the
    # opener prints NO business noun ("these 3 in houston got ...": not
    # "restaurants", not "companies"), whatever the prospect's niche. Restaurants.
    bare: bool = False
    dm: str = ""
    need: str = ""
    extra: dict = field(default_factory=dict)

    # --- rendering -----------------------------------------------------------
    def predicate(self, leads: list[Lead]) -> str:
        if len(leads) == 1:
            return self.said(leads[0])
        return self.plural(leads) if callable(self.plural) else self.plural

    def said(self, lead: Lead) -> str:
        return self.singular(lead) if callable(self.singular) else self.singular

    def why_for(self, leads: list[Lead]) -> str:
        why = self.why(leads) if callable(self.why) else self.why
        if not why:
            return ""
        said = why[1] if len(leads) == 1 else why[0]
        # 2026-11-12, the user: emails ran 101 words, the long reasons first
        # among the causes. A reason over WHY_MAX_WORDS is left out; the
        # predicate and the leads still say what happened.
        return said if len(said.split()) <= WHY_MAX_WORDS else ""

    def detail_for(self, lead: Lead) -> str:
        return self.detail(lead) if self.detail else ""

    def phrase(self, lead: Lead) -> str:
        return self.line(lead) if callable(self.line) else self.line

    def sentence(self, lead: Lead) -> str:
        """Email 2's predicate for one lead, its detail folded in."""
        if self.followup:
            return self.followup(lead)
        detail = self.detail_for(lead)
        return f"{self.said(lead)} ({detail})" if detail else self.said(lead)

    def short_for(self, leads: list[Lead], n: int | None = None) -> str:
        """The short subject's WHAT for these leads (`n` overrides the count;
        no leads = the generic words)."""
        short = self.short(leads) if callable(self.short) else self.short
        n = len(leads) if n is None else n
        return short[1] if n == 1 else short[0]

    def noun_for(self, lead: Lead) -> tuple[str, str] | None:
        return self.noun(lead) if callable(self.noun) else self.noun

    def generic_plural(self) -> str:
        return self.plural([]) if callable(self.plural) else self.plural

    def generic_singular(self) -> str:
        """The singular predicate with no lead to read (a subject WHAT)."""
        return self.said(Lead(id="", company="", signal_type=""))

    @property
    def subject_plural(self) -> str:
        return f"that {self.generic_plural()}"

    @property
    def flags_what(self) -> str:
        return self.dm or f"that {self.generic_plural()}"

    @property
    def need_clause(self) -> str:
        return self.need or f"that {self.generic_plural()}"


# --- per-type helpers ----------------------------------------------------------

def _late_months(key: str) -> Callable[[Lead], str]:
    def detail(lead: Lead) -> str:
        m = _months(_payload(lead).get(key))
        return f"{m} late" if m else ""
    return detail


def _late_line(what: str, key: str) -> Callable[[Lead], str]:
    """The mixed-gift line in Row 1's words: "filed their federal audit 7
    months late"."""
    def line(lead: Lead) -> str:
        m = _months(_payload(lead).get(key))
        return f"filed {what} {m} late" if m else f"filed {what} late"
    return line


def _late_followup(what: str, key: str) -> Callable[[Lead], str]:
    """"filed its federal single audit 7 months late"."""
    def said(lead: Lead) -> str:
        m = _months(_payload(lead).get(key))
        return f"filed {what} {m} late" if m else f"filed {what} late"
    return said


def _instrument(lead: Lead) -> str:
    return "warrant" if "warrant" in str(_payload(lead).get("instrument") or "").lower() \
        else "lien"


def _state_tax_kind(leads: list[Lead]) -> str:
    kinds = {_instrument(ld) for ld in leads}
    return "warrants" if kinds == {"warrant"} else "liens" if kinds == {"lien"} \
        else "liens or warrants"


def _state_tax_plural(leads: list[Lead]) -> str:
    return f"had state tax {_state_tax_kind(leads)} filed against them"


def _state_tax_one(lead: Lead) -> str:
    return f"had a state tax {_instrument(lead)} filed against it"


def _state_tax_short(leads: list[Lead]) -> tuple[str, str]:
    kind = _state_tax_kind(leads) if leads else "liens"
    one = "warrant" if kind == "warrants" else "lien"
    return f"with state tax {kind}", f"with a state tax {one}"


def _ui_plural(leads: list[Lead]) -> str:
    return "had liens filed against them for unpaid unemployment tax"


def _ui_one(lead: Lead) -> str:
    return "had a lien filed against it for unpaid unemployment tax"


def _ca_tax_detail(lead: Lead) -> str:
    authority = str(_payload(lead).get("authority") or _payload(lead).get("list") or "").lower()
    if "franchise" in authority or "ftb" in authority:
        return "corporate tax"
    if "cdtfa" in authority or "tax and fee" in authority:
        return "sales tax"
    return ""


_PROVIDER = {
    "HOME HEALTH AGENCY": "home health agency", "HOSPICE": "hospice",
    "RURAL HEALTH CLINIC": "rural health clinic", "HOSPITAL": "hospital",
    "FEDERALLY QUALIFIED HEALTH CENTER": "health center",
    "SKILLED NURSING FACILITY": "nursing facility",
}


def _provider_kind(lead: Lead) -> str:
    text = str(_payload(lead).get("provider_type_text") or "").upper()
    for key, word in _PROVIDER.items():
        if key in text:
            return word
    return ""


def _new_medicare(lead: Lead) -> str:
    """Email 2: "newly enrolled in medicare as a hospice" (every kind here
    takes "a")."""
    kind = _provider_kind(lead)
    return f"newly enrolled in medicare as a {kind}" if kind else "newly enrolled in medicare"


def _omig_why(leads: list[Lead]) -> tuple[str, str] | None:
    if leads and all(_payload(ld).get("amount") for ld in leads):
        return ("and each report says money is owed back",
                "and the report says money is owed back")
    return None


def _late_filing_detail(lead: Lead) -> str:
    p = _payload(lead)
    form = str(p.get("form") or "").upper().replace("NT ", "").strip().lower()
    still = "" if p.get("late_report_filed_on") else "not on edgar yet"
    return ", ".join(w for w in (form, still) if w)


def _opinion(lead: Lead) -> str:
    return str(_payload(lead).get("opinion") or "").lower()


def _bd_detail(lead: Lead) -> str:
    m = _months(_payload(lead).get("days_after_year_end"))
    return f"{m} after" if m else ""


def _bd_followup(lead: Lead) -> str:
    m = _months(_payload(lead).get("days_after_year_end"))
    return (f"filed its annual audited report with the sec {m} after year end" if m
            else "filed its annual audited report with the sec months after year end")


def _fy(lead: Lead) -> str:
    fy = str(_payload(lead).get("fiscal_year_checked") or "")
    return fy[:4] if fy[:4].isdigit() else ""


def _rega_plural(leads: list[Lead]) -> str:
    year = _one([_fy(ld) for ld in leads]) if leads else ""
    return (f"don't have a form 1-k for fiscal {year} on edgar yet" if year
            else "don't have their latest form 1-k on edgar yet")


def _rega_one(lead: Lead) -> str:
    year = _fy(lead)
    return (f"doesn't have a form 1-k for fiscal {year} on edgar yet" if year
            else "doesn't have its latest form 1-k on edgar yet")


def _charter_fy(lead: Lead) -> str:
    fy = str(_payload(lead).get("fy_missing") or "").upper().replace("FY", "").strip()
    return fy if fy[:4].isdigit() else ""


def _charter_plural(leads: list[Lead]) -> str:
    fy = _one([_charter_fy(ld) for ld in leads]) if leads else ""
    what = f"their {fy} audits" if fy else "their latest audits"
    return f"don't have {what} posted by the state's auditor general yet"


def _charter_one(lead: Lead) -> str:
    fy = _charter_fy(lead)
    return f"doesn't have its {fy + ' ' if fy else 'latest '}audit posted by the state's " \
           "auditor general yet"


def _report_year(lead: Lead) -> str:
    y = str(_payload(lead).get("report_year") or "")
    return y if y.isdigit() else ""


def _water_plural(leads: list[Lead]) -> str:
    y = _one([_report_year(ld) for ld in leads]) if leads else ""
    return f"don't have {'a ' + y if y else 'their latest'} annual report posted by the cpuc yet"


def _water_one(lead: Lead) -> str:
    y = _report_year(lead)
    return f"doesn't have {'a ' + y if y else 'its latest'} annual report posted by the cpuc yet"


def _hcm_reason(lead: Lead) -> str:
    return str(_payload(lead).get("reason") or "").strip().lower()


# What the leads ARE, when it is not "companies" / "nonprofits".
_PROVIDERS = ("provider", "providers")
_CONTRACTORS = ("contractor", "contractors")
_SCHOOLS = ("school", "schools")
_LOCAL_GOV = ("local government", "local governments")
_UNIONS = ("union", "unions")
_BROKERS = ("brokerage", "brokerages")
_CU = ("credit union", "credit unions")
_BD = ("broker-dealer", "broker-dealers")
_ENGINEERS = ("engineering firm", "engineering firms")


def _local_body(lead: Lead) -> tuple[str, str]:
    """A school district is a school to the reader, not a "local government"."""
    return _SCHOOLS if lead.niche == "k12_school" else _LOCAL_GOV

_AUDIT_WHY = ("and each must show it's fixed by its next audit",
              "and it must show it's fixed by its next audit")
_GRANT_RULES = ("so each now has strict federal reporting rules",
                "so it now has strict federal reporting rules")


DUTIES: dict[str, Duty] = {
    # --- Nonprofit duty (batch 1): the org's own 990 or its federal audit ------
    "nonprofit_single_audit_not_done": Duty(
        plural="said on their 990s that a required federal audit wasn't done",
        singular="said on its 990 that a required federal audit wasn't done",
        why=("and none is on file with the clearinghouse yet",
             "and none is on file with the clearinghouse yet"),
        line="990 says a required federal audit wasn't done",
        short=("with a federal audit not done", "with a federal audit not done"),
        dm="whose 990s say a required federal audit wasn't done"),
    "nonprofit_single_audit_late": Duty(
        plural="filed their federal single audits late",
        singular="filed its federal single audit late",
        detail=_late_months("fac_days_late"),
        followup=_late_followup("its federal single audit", "fac_days_late"),
        line=_late_line("their federal audit", "fac_days_late"),
        short=("with late federal audits", "with a late federal audit"),
        dm="filing their federal audits late"),
    "nonprofit_asset_diversion": Duty(
        plural="reported a significant diversion of assets on their 990s",
        singular="reported a significant diversion of assets on its 990",
        line="reported a diversion of assets on their 990",
        short=("that reported asset diversions", "that reported an asset diversion"),
        dm="reporting a diversion of assets on their 990s"),
    "nonprofit_going_concern": Duty(
        plural="got a going-concern warning in their federal audits",
        singular="got a going-concern warning in its federal audit",
        line="going-concern warning in their federal audit",
        short=("with going-concern warnings", "with a going-concern warning"),
        dm="getting going-concern warnings in their audits"),
    "nonprofit_ubi_no_990t": Duty(
        plural="reported business income on their 990s but no 990-t",
        singular="reported business income on its 990 but no 990-t",
        why=("and the irs has no 990-t from them for that year",
             "and the irs has no 990-t from it for that year"),
        line="business income on their 990, no 990-t filed",
        short=("missing a 990-t", "missing a 990-t"),
        dm="reporting business income with no 990-t"),
    "nonprofit_excess_benefit": Duty(
        plural="reported an excess benefit transaction with an insider on their 990s",
        singular="reported an excess benefit transaction with an insider on its 990",
        line="reported an insider excess benefit on their 990",
        short=("with excess benefit transactions", "with an excess benefit transaction"),
        dm="reporting excess benefit transactions with insiders"),
    # 2026-11-03: the org's own Form 990 (Nonprofit `budget.severe_deficit_low_cash`):
    # expenses 5%+ over revenue in the current AND the prior-year column, cash and
    # savings under a month of expenses. Says only what the return says: no
    # "struggling", no "running out", no dollar figure.
    "nonprofit_deficit_low_cash": Duty(
        plural="reported spending more than they took in two years running, with under a month of cash left",
        singular="reported spending more than it took in two years running, with under a month of cash left",
        line="two years of deficits, little cash left",
        short=("with 2 years of deficits", "with 2 years of deficits"),
        dm="reporting two years of deficits and little cash"),
    "nonprofit_state_audit_line_no_audit": Duty(
        plural="reported no audit on their 990s, with revenue over a state audit line",
        singular="reported no audit on its 990, with revenue over a state audit line",
        line="reported no audit, revenue over a state line",
        short=("with no audit on their 990s", "with no audit on its 990"),
        dm="reporting no audit above a state audit line"),
    "nonprofit_exemption_revoked": Duty(
        plural="lost their tax-exempt status for not filing a return three years running",
        singular="lost its tax-exempt status for not filing a return three years running",
        line="lost their tax exemption for not filing returns",
        short=("that lost tax-exempt status", "that lost its tax-exempt status"),
        dm="losing their tax-exempt status"),
    "nonprofit_questioned_costs": Duty(
        plural="had costs questioned in their federal audits",
        singular="had costs questioned in its federal audit",
        why=_AUDIT_WHY,
        line="auditors questioned costs on their federal grants",
        short=("with questioned costs", "with questioned costs"),
        dm="whose auditors questioned costs"),

    # --- Benefits: the employer's own Form 5500 --------------------------------
    "plan_audit_first_due": Duty(
        plural="have retirement plans that passed 120 participants",
        singular="has a retirement plan that passed 120 participants",
        why=("so each now needs its first independent plan audit",
             "so it now needs its first independent plan audit"),
        line="plan passed 120 participants, first audit due",
        short=("needing their first plan audit", "needing its first plan audit"),
        dm="whose retirement plans just crossed the audit line"),
    "plan_audit_first_filed": Duty(
        plural="filed their first audited form 5500s",
        singular="filed its first audited form 5500",
        why=("so each needs a plan audit every year now",
             "so it needs a plan audit every year now"),
        line="first audited form 5500, plan audit every year",
        short=("with their first plan audits", "with its first plan audit"),
        dm="filing their first plan audits"),
    "plan_late_contributions": Duty(
        plural="reported late deposits of employee contributions on their latest form 5500s",
        singular="reported late deposits of employee contributions on its latest form 5500",
        line="late employee contributions, per their form 5500",
        short=("with late plan deposits", "with late plan deposits"),
        dm="reporting late plan deposits on their form 5500s"),
    "plan_termination_pending": Duty(
        plural="reported a decision to end a benefit plan on their latest form 5500s",
        singular="reported a decision to end a benefit plan on its latest form 5500",
        why=("so each still owes a final plan return", "so it still owes a final plan return"),
        line="ending a benefit plan, final return still owed",
        short=("ending a benefit plan", "ending a benefit plan"),
        dm="ending a benefit plan"),
    "plan_prohibited_transaction": Duty(
        plural="reported a prohibited transaction in a benefit plan on their latest form 5500s",
        singular="reported a prohibited transaction in a benefit plan on its latest form 5500",
        line="prohibited plan transaction on their form 5500",
        short=("with prohibited plan transactions", "with a prohibited plan transaction"),
        dm="reporting prohibited plan transactions"),
    "pension_unpaid_min_contribution": Duty(
        plural="reported unpaid minimum pension contributions on their latest form 5500s",
        singular="reported unpaid minimum pension contributions on its latest form 5500",
        line="unpaid minimum pension contributions on their 5500",
        short=("with unpaid pension contributions", "with unpaid pension contributions"),
        dm="reporting unpaid pension contributions"),
    "welfare_plan_audit_threshold": Duty(
        plural="have trust-funded benefit plans that reached 100 participants",
        singular="has a trust-funded benefit plan that reached 100 participants",
        why=("so each now needs a plan audit", "so it now needs a plan audit"),
        line="trust-funded benefit plan at 100+, audit needed",
        short=("whose benefit plans need audits", "whose benefit plan needs an audit"),
        dm="whose benefit plans now need an audit"),
    "plan_fraud_loss": Duty(
        plural="reported a fraud loss in a benefit plan on their latest form 5500s",
        singular="reported a fraud loss in a benefit plan on its latest form 5500",
        line="reported a fraud loss in a benefit plan",
        short=("with fraud losses in a plan", "with a fraud loss in a plan"),
        dm="reporting fraud losses in their plans"),
    "plan_audit_opinion_modified": Duty(
        plural="got a modified opinion from their plan auditors on their latest form 5500s",
        singular="got a modified opinion from its plan auditor on its latest form 5500",
        detail=_opinion,
        line="their plan auditor gave a modified opinion",
        short=("with modified plan audit opinions", "with a modified plan audit opinion"),
        dm="getting modified plan audit opinions"),

    # --- Tax trouble: liens, warrants, delinquency lists -----------------------
    "state_tax_lien": Duty(
        plural=_state_tax_plural, singular=_state_tax_one,
        line=lambda ld: f"state tax {_instrument(ld)} filed against them",
        short=_state_tax_short,
        dm="with state tax liens or warrants filed against them"),
    "federal_tax_lien": Duty(
        plural="had federal tax liens filed against them",
        singular="had a federal tax lien filed against it",
        line="federal tax lien filed against them",
        short=("with federal tax liens", "with a federal tax lien"),
        dm="with federal tax liens filed against them"),
    "unemployment_tax_lien": Duty(
        plural=_ui_plural, singular=_ui_one,
        line="lien filed for unpaid unemployment tax",
        short=("with unemployment tax liens", "with an unemployment tax lien"),
        dm="with liens for unpaid unemployment tax"),
    "top_tax_delinquent": Duty(
        plural="are on one of the state's top 500 tax delinquent lists",
        singular="is on one of the state's top 500 tax delinquent lists",
        detail=_ca_tax_detail,
        line="on a california top 500 tax delinquent list",
        short=("on the state's top 500 tax list", "on the state's top 500 tax list"),
        dm="on the state's top 500 tax delinquent lists"),
    # Texas (2026-11-05): the Comptroller's MAILING address (often an agent's)
    # is the lead's place, so "texas" is named, never "the state".
    "charter_forfeited_for_tax": Duty(
        plural="had their texas charters forfeited over franchise tax",
        singular="had its texas charter forfeited over franchise tax",
        why=("so each must catch up its filings to reinstate",
             "so it must catch up its filings to reinstate"),
        line="texas charter forfeited over franchise tax",
        short=("with forfeited texas charters", "with a forfeited texas charter"),
        dm="who lost their texas charter over franchise tax"),
    "franchise_tax_forfeited": Duty(
        plural="lost the right to do business in texas over franchise tax",
        singular="lost the right to do business in texas over franchise tax",
        why=("so each must catch up filings to get it back",
             "so it must catch up filings to get it back"),
        line="lost texas business rights over franchise tax",
        short=("that lost texas business rights", "that lost texas business rights"),
        dm="who lost the right to do business in texas over franchise tax"),
    # Minnesota (2026-11-05): Revenue's liquor / cannabis posting lists and its
    # revoked sales tax permits (the state from the city: Inventory normalize).
    "tax_delinquent_posting": Duty(
        plural="were posted by the state as behind on filing or paying their taxes",
        singular="was posted by the state as behind on filing or paying its taxes",
        line="posted by the state as behind on taxes",
        short=("posted as tax-delinquent", "posted as tax-delinquent"),
        dm="posted by the state as behind on their taxes"),
    "sales_tax_permit_revoked": Duty(
        plural="had their sales tax permits revoked over unpaid sales tax",
        singular="had its sales tax permit revoked over unpaid sales tax",
        why=("so each can't legally make taxable sales until reinstated",
             "so it can't legally make taxable sales until reinstated"),
        line="sales tax permit revoked over unpaid sales tax",
        short=("with revoked sales tax permits", "with a revoked sales tax permit"),
        dm="whose sales tax permits were revoked"),

    # --- Healthcare: Medicare enrollments and ownership changes ---------------
    "medicare_new_part_a_provider": Duty(
        plural="newly enrolled in medicare", singular="newly enrolled in medicare",
        why=("so each owes its first medicare cost report",
             "so it owes its first medicare cost report"),
        detail=_provider_kind, followup=_new_medicare,
        line="new medicare provider, first cost report ahead",
        short=("new to medicare", "new to medicare"),
        noun=_PROVIDERS, dm="newly enrolling in medicare"),
    "snf_change_of_ownership": Duty(
        plural="took over nursing homes in a medicare change of ownership",
        singular="took over a nursing home in a medicare change of ownership",
        why=("so each now files its own medicare cost reports",
             "so it now files its own medicare cost reports"),
        line="took over a nursing home from another operator",
        short=("that took over nursing homes", "that took over a nursing home"),
        dm="taking over nursing homes"),
    "hospital_change_of_ownership": Duty(
        plural="took over hospitals in a medicare change of ownership",
        singular="took over a hospital in a medicare change of ownership",
        why=("so each now files its own medicare cost reports",
             "so it now files its own medicare cost reports"),
        line="took over a hospital from another operator",
        short=("that took over hospitals", "that took over a hospital"),
        dm="taking over hospitals"),
    "ny_omig_final_audit": Duty(
        plural="got final medicaid audit reports from the state",
        singular="got a final medicaid audit report from the state",
        why=_omig_why,
        line="final new york medicaid audit report",
        short=("with final medicaid audits", "with a final medicaid audit"),
        noun=_PROVIDERS, dm="getting final state medicaid audits"),
    "hrsa_new_health_center": Duty(
        plural="got their first federal health center grants",
        singular="got its first federal health center grant",
        why=_GRANT_RULES,
        line="first federal health center grant",
        short=("with first hrsa grants", "with a first hrsa grant"),
        noun=("health center", "health centers"), org=True,
        dm="getting their first federal health center grant"),

    # --- Property ------------------------------------------------------------------
    "hud_new_owner": Duty(
        plural="became owners of hud-assisted housing",
        singular="became the owner of hud-assisted housing",
        why=("so each owes hud yearly financial statements",
             "so it owes hud yearly financial statements"),
        line="new owner of hud-assisted housing",
        short=("now owning hud-assisted housing", "now owning hud-assisted housing"),
        dm="becoming owners of hud-assisted housing"),
    "tcac_placed_in_service": Duty(
        plural="placed tax-credit housing projects in service",
        singular="placed a tax-credit housing project in service",
        line="tax-credit housing project placed in service",
        short=("with new tax-credit housing", "with new tax-credit housing"),
        dm="placing tax-credit housing in service"),
    "ca_dre_trust_fund_discipline": Duty(
        plural="were disciplined by the state's real estate department over trust-fund rules",
        singular="was disciplined by the state's real estate department over trust-fund rules",
        line="disciplined by the state over trust funds",
        short=("disciplined over trust funds", "disciplined over trust funds"),
        noun=_BROKERS, dm="disciplined over trust-fund rules"),
    "ca_dre_audit_discipline": Duty(
        plural="were disciplined by the state's real estate department after an audit",
        singular="was disciplined by the state's real estate department after an audit",
        line="disciplined by the state after an audit",
        short=("disciplined after an audit", "disciplined after an audit"),
        noun=_BROKERS, dm="disciplined after a regulator's audit"),
    "nc_rec_trust_account_discipline": Duty(
        plural="were disciplined by the state's real estate commission over trust accounts",
        singular="was disciplined by the state's real estate commission over its trust account",
        line="disciplined by the state over trust accounts",
        short=("disciplined over trust accounts", "disciplined over trust accounts"),
        noun=_BROKERS, dm="disciplined over trust accounts"),
    "fl_condo_new_association": Duty(
        plural="manage newly recorded condos",
        singular="manages a newly recorded condo",
        why=("and each owes its owners a yearly financial report",
             "and it owes its owners a yearly financial report"),
        line="manages a newly recorded condo",
        short=("for newly recorded condos", "for a newly recorded condo"),
        noun=("condo association", "condo associations"), org=True,
        dm="managing newly recorded condos"),

    # --- Securities: SEC filings and NCUA call reports ----------------------------
    "late_filing_notice": Duty(
        plural="filed late-filing notices with the sec",
        singular="filed a late-filing notice with the sec",
        detail=_late_filing_detail,
        line="filed a late-filing notice with the sec",
        short=("with sec late-filing notices", "with an sec late-filing notice"),
        dm="filing late-filing notices with the sec"),
    "auditor_change": Duty(
        plural="changed auditors, per their sec filings",
        singular="changed auditors, per its sec filings",
        line="changed auditors, per an sec filing",
        short=("that changed auditors", "that changed auditors"),
        dm="changing auditors"),
    "restatement_nonreliance": Duty(
        plural="told investors not to rely on their past financial statements",
        singular="told investors not to rely on its past financial statements",
        line="said their past financials can't be relied on",
        short=("with unreliable past financials", "with unreliable past financials"),
        dm="telling investors not to rely on past financials"),
    "nasdaq_late_filing_deficiency": Duty(
        plural="got nasdaq notices for late sec reports",
        singular="got a nasdaq notice for late sec reports",
        line="nasdaq notice for late sec reports",
        short=("with nasdaq late-filing notices", "with a nasdaq late-filing notice"),
        dm="getting nasdaq late-filing notices"),
    "bd_annual_audit_late": Duty(
        plural="filed their annual audited reports with the sec months after year end",
        singular="filed its annual audited report with the sec months after year end",
        detail=_bd_detail, followup=_bd_followup,
        line="annual audited report filed months after year end",
        short=("with delayed annual audits", "with a delayed annual audit"),
        noun=_BD, dm="filing annual audits months after year end"),
    "bd_material_weakness": Duty(
        plural="flagged a material weakness on their annual audited reports",
        singular="flagged a material weakness on its annual audited report",
        line="material weakness flagged on their annual audit",
        short=("with material weaknesses", "with a material weakness"),
        noun=_BD, dm="flagging material weaknesses"),
    "cu_approaching_fs_audit": Duty(
        plural="are nearing the size where they must get a full audit",
        singular="is nearing the size where it must get a full audit",
        line="nearing the size that needs a full audit",
        short=("nearing the full-audit line", "nearing the full-audit line"),
        noun=_CU, org=True, dm="nearing the size that needs a full audit"),
    "cu_over_500m_no_fs_audit": Duty(
        plural="passed the size where they must get a full audit, and their last one wasn't",
        singular="passed the size where it must get a full audit, and its last one wasn't",
        line="past the full-audit line, last audit wasn't one",
        short=("past the full-audit line", "past the full-audit line"),
        noun=_CU, org=True, dm="past the size that needs a full audit"),
    "cu_stale_audit": Duty(
        plural="haven't had an audit in over two years",
        singular="hasn't had an audit in over two years",
        why=("though they need one every year", "though it needs one every year"),
        line="no audit in over two years",
        short=("with audits over two years old", "with an audit over two years old"),
        noun=_CU, org=True, dm="with audits over two years old"),
    "rega_tier2_1k_missing": Duty(
        plural=_rega_plural, singular=_rega_one,
        line="their latest form 1-k isn't on edgar",
        short=("without a form 1-k on edgar", "without a form 1-k on edgar"),
        dm="with no form 1-k on edgar"),

    # --- Public sector: schools, local governments, unions --------------------------
    "college_heightened_cash_monitoring": Duty(
        plural="were newly put on federal heightened cash monitoring",
        singular="was newly put on federal heightened cash monitoring",
        why=("so each must pay student aid from its own cash",
             "so it must pay student aid from its own cash"),
        detail=_hcm_reason,
        line="newly on federal heightened cash monitoring",
        short=("on federal cash monitoring", "on federal cash monitoring"),
        noun=_SCHOOLS, org=True, dm="newly put on federal cash monitoring"),
    "proprietary_90_10_near_limit": Duty(
        plural="are at or near the 90/10 cap on federal student aid revenue",
        singular="is at or near the 90/10 cap on federal student aid revenue",
        why=("and two years over it ends their aid eligibility",
             "and two years over it ends its aid eligibility"),
        detail=lambda ld: "over the cap" if _payload(ld).get("over_90") else "",
        line="at or near the 90/10 federal aid cap",
        short=("near the 90/10 aid cap", "near the 90/10 aid cap"),
        noun=_SCHOOLS, org=True, dm="near the 90/10 federal aid cap"),
    "wi_choice_school_new": Duty(
        plural="joined the state's private school choice program",
        singular="joined the state's private school choice program",
        why=("so each now needs an independent audit every year",
             "so it now needs an independent audit every year"),
        line="new to the state's choice program, yearly audit",
        short=("new to school choice", "new to school choice"),
        noun=_SCHOOLS, org=True, dm="joining the state's school choice program"),
    "charter_audit_missing": Duty(
        plural=_charter_plural, singular=_charter_one,
        line="latest audit not posted by the state yet",
        short=("with no audit posted yet", "with no audit posted yet"),
        noun=("charter school", "charter schools"), org=True,
        dm="with no audit posted yet"),
    "local_gov_financial_report_late": Duty(
        plural="were listed by their state as late on a required annual financial report",
        singular="was listed by its state as late on a required annual financial report",
        line="listed late on a required annual financial report",
        short=("late on a required report", "late on a required report"),
        noun=_local_body, org=True, dm="listed late on required financial reports"),
    "local_gov_single_audit_late": Duty(
        plural="filed their federal single audits late",
        singular="filed its federal single audit late",
        detail=_late_months("days_late"),
        followup=_late_followup("its federal single audit", "days_late"),
        line=_late_line("their federal audit", "days_late"),
        short=("with late federal audits", "with a late federal audit"),
        noun=_local_body, org=True, dm="filing their federal audits late"),
    "union_lm_report_late": Duty(
        plural="filed their yearly labor department financial reports late",
        singular="filed its yearly labor department financial report late",
        detail=_late_months("days_past_due"),
        followup=_late_followup("its yearly labor department financial report",
                                "days_past_due"),
        line=_late_line("their yearly labor department report", "days_past_due"),
        short=("with late financial reports", "with a late financial report"),
        noun=_UNIONS, org=True, dm="filing their labor department reports late"),
    "union_funds_shortage": Duty(
        plural="reported a loss or shortage of funds on their labor department reports",
        singular="reported a loss or shortage of funds on its labor department report",
        line="reported a loss or shortage of funds",
        short=("that reported a funds shortage", "that reported a funds shortage"),
        noun=_UNIONS, org=True, dm="reporting a loss or shortage of funds"),

    # --- Specialty: permits, licenses, rates and credits ------------------------------
    "ttb_new_winery_permit": Duty(
        plural="got new federal winery permits",
        singular="got a new federal winery permit",
        why=("so each now files federal excise tax returns",
             "so it now files federal excise tax returns"),
        line="new federal winery permit, excise returns start",
        short=("with new federal permits", "with a new federal permit"),
        noun=("winery", "wineries"), dm="getting new federal winery permits"),
    "ttb_new_distillery_permit": Duty(
        plural="got new federal distillery permits",
        singular="got a new federal distillery permit",
        why=("so each now files federal excise tax returns",
             "so it now files federal excise tax returns"),
        line="new federal distillery permit, excise returns start",
        short=("with new federal permits", "with a new federal permit"),
        noun=("distillery", "distilleries"), dm="getting new federal distillery permits"),
    "ae_txdot_overhead_approval_lapsed": Duty(
        plural="had their txdot overhead approvals run out with no new one listed",
        singular="had its txdot overhead approval run out with no new one listed",
        why=("and renewing takes a new overhead audit",
             "and renewing takes a new overhead audit"),
        line="txdot overhead approval ran out, none newer listed",
        short=("with lapsed txdot overhead rates", "with a lapsed txdot overhead rate"),
        noun=_ENGINEERS, dm="whose txdot overhead approvals ran out"),
    "ae_caltrans_first_icr_acceptance": Duty(
        plural="got their first caltrans indirect cost rate acceptance",
        singular="got its first caltrans indirect cost rate acceptance",
        why=("so each has to update its rate every fiscal year",
             "so it has to update its rate every fiscal year"),
        line="first caltrans indirect cost rate acceptance",
        short=("with new caltrans overhead rates", "with a new caltrans overhead rate"),
        noun=_ENGINEERS, dm="getting their first caltrans overhead rate"),
    "water_ca_annual_report_missing": Duty(
        plural=_water_plural, singular=_water_one,
        line="latest annual report not posted by the cpuc",
        short=("with no cpuc report posted", "with no cpuc report posted"),
        noun=("water company", "water companies"), dm="with no cpuc annual report posted"),
    "nv_casino_new_nonrestricted_license": Duty(
        plural="were approved for nonrestricted gaming licenses",
        singular="was approved for a nonrestricted gaming license",
        why=("so each now files monthly gaming tax returns",
             "so it now files monthly gaming tax returns"),
        line="new nevada gaming license, monthly tax returns",
        short=("with new gaming licenses", "with a new gaming license"),
        dm="getting new nonrestricted gaming licenses"),
    "film_ca_credit_allocated": Duty(
        plural="were allocated state film tax credits",
        singular="was allocated a state film tax credit",
        why=("so each needs a cpa report to claim it",
             "so it needs a cpa report to claim it"),
        line="california film tax credit, cpa report needed",
        short=("with new film tax credits", "with a new film tax credit"),
        noun=("production company", "production companies"),
        dm="getting state film tax credits"),
    "film_nj_credit_approved": Duty(
        plural="were approved for state film tax credits not yet certified",
        singular="was approved for a state film tax credit not yet certified",
        why=("so each needs a cpa's verification report",
             "so it needs a cpa's verification report"),
        line="nj film tax credit approved, not yet certified",
        short=("with uncertified film credits", "with an uncertified film credit"),
        noun=("production company", "production companies"),
        dm="holding uncertified state film credits"),

    # --- Construction duty ---------------------------------------------------------------
    "construction_first_prevailing_wage_intent": Duty(
        plural="started their first public jobs paying state wage rates",
        singular="started its first public job paying state wage rates",
        why=("so each must report wages paid when the job ends",
             "so it must report wages paid when the job ends"),
        line="first public job paying state wage rates",
        short=("on their first public jobs", "on its first public job"),
        noun=_CONTRACTORS, dm="starting their first state public jobs"),
    "construction_nv_license_limit": Duty(
        plural="got new state contractor licenses",
        singular="got a new state contractor license",
        line="new nevada contractor license",
        short=("with new contractor licenses", "with a new contractor license"),
        noun=_CONTRACTORS, dm="getting new state contractor licenses"),
    "construction_fl_stop_work_order": Duty(
        plural="were served workers' comp stop-work orders by the state",
        singular="was served a workers' comp stop-work order by the state",
        why=("and none shows as lifted yet", "and it doesn't show as lifted yet"),
        line="florida workers' comp stop-work order, not lifted",
        short=("with stop-work orders", "with a stop-work order"),
        noun=_CONTRACTORS, dm="served workers' comp stop-work orders"),

    # --- Federal duty ------------------------------------------------------------------------
    "govcon_first_sbir_phase2": Duty(
        plural="won their first sbir phase ii awards",
        singular="won its first sbir phase ii award",
        why=_GRANT_RULES,
        line="first sbir phase ii award",
        short=("with first sbir phase ii awards", "with a first sbir phase ii award"),
        dm="winning their first sbir phase ii award"),
}



# --- Nonprofit: the 990 filing gaps and new nonprofits (approved 2026-10-30) ---
# The 990 filing gaps: a charity with no Form 990 (or 990-EZ / 990-N) in the
# IRS's public records for one or two years past the extended deadline
# (Nonprofit `filinggap.py`). Three years in a row revokes its exemption by
# law (IRC 6033(j)). The record shows an ABSENCE on a date, so the words are
# "no 990 on irs public record", never "didn't file" or "missed": a return
# can be in the IRS's hands for weeks before it is published (~5% of flags,
# measured). Only the year is said per lead (the form's year); "next one due
# soon" when the next deadline is within 90 days.

def _gap_years(lead: Lead) -> str:
    years = [str(y) for y in _payload(lead).get("missed_tax_years") or []]
    detail = " and ".join(f"fy{y}" for y in years)
    if _payload(lead).get("next_deadline_within_90_days") is True:
        detail = f"{detail}, next one due soon" if detail else "next one due soon"
    return detail


# New nonprofits (Nonprofit `newnp.py`). `nonprofit_new_501c3`: a state
# registry formation within 12 months of the read and an IRS 501(c)(3) letter
# within 6, IRS filing code 01 ("990 or 990-EZ"): "newly incorporated", never
# "brand new" or "just started" (the state date is when it incorporated, which
# can follow when it began). `nonprofit_first_990`: a 990 / 990-EZ with the
# Initial return box ticked, corroborated by the IRS's own records. The form
# is named as filed (a 990-EZ is never a "990" alone, never a "full 990"), and
# the ONLY no-help claim is "filed without a paid preparer", said only when
# the return names neither a preparer firm nor a preparer
# (`paid_preparer_listed` is False; None = not read, so nothing is said).

def _first_990_detail(lead: Lead) -> str:
    # 2026-11-06: not "990 for fy2025" (the heading already says it filed its
    # first return); only the one fact a reader can use.
    return "no paid preparer" if _payload(lead).get("paid_preparer_listed") is False else ""


HELD_DUTIES: dict[str, Duty] = {
    "nonprofit_990_missed_1yr": Duty(
        plural="have no 990 on irs public record for a year past due",
        singular="has no 990 on irs public record for a year past due",
        why=("and three years running costs a charity its exemption",
             "and three years running costs a charity its exemption"),
        detail=_gap_years,
        line="no 990 on file for a past-due year",
        short=("with no 990 on file", "with no 990 on file"),
        dm="with no 990 on file for a year past due"),
    "nonprofit_990_missed_2yr": Duty(
        plural="have no 990 on irs public record for two years running",
        singular="has no 990 on irs public record for two years running",
        why=("so a third would cost each its tax exemption",
             "so a third would cost it its tax exemption"),
        detail=_gap_years,
        line="no 990 on file for two years running",
        short=("with no 990 on file for 2 years", "with no 990 on file for 2 years"),
        dm="with no 990 on file for two years running"),
    "nonprofit_new_501c3": Duty(
        plural="are newly incorporated and recognized as 501(c)(3)s by the irs",
        singular="is newly incorporated and recognized as a 501(c)(3) by the irs",
        why=("so each must file a 990 every year",
             "so it must file a 990 every year"),
        line="newly incorporated, new 501(c)(3) status",
        short=("newly recognized as 501(c)(3)s", "newly recognized as a 501(c)(3)"),
        dm="newly recognized as 501(c)(3)s"),
    "nonprofit_first_990": Duty(
        plural="filed their first annual returns with the irs",
        singular="filed its first annual return with the irs",
        detail=_first_990_detail,
        line="first annual return filed with the irs",
        short=("that filed their first irs returns", "that filed its first irs return"),
        dm="filing their first annual returns with the irs"),
}
# --- Startups (2026-10-30): SEC Form D, US tech companies -----------------------
# The raise claim is allowed for THIS source only (CLAUDE.md): every lead links
# its own Form D. No dollar figure, no date, no "round", no "first funding".
# "tech startups" only when every lead was incorporated within five years
# (`noun_mixed` covers a gift that mixes them: "tech companies").
_TECH_CO = ("tech company", "tech companies")


def _startup_noun(lead: Lead) -> tuple[str, str]:
    young = _payload(lead).get("incorporated_within_five_years") is True
    return ("tech startup", "tech startups") if young else _TECH_CO


_RAISE_WHY = ("so each has a new raise to book",
              "so it has a new raise to book")

# 2026-11-05 the user held Form D ("a very commoditized signal"), then allowed
# it for firms that serve startups only (gift.engine.not_a_buyer_for).
DUTIES.update({
    "startup_first_form_d": Duty(
        plural="filed their first form d with the sec",
        singular="filed its first form d with the sec",
        why=_RAISE_WHY,
        line="filed its first form d with the sec",
        short=("with a first sec form d", "with a first sec form d"),
        noun=_startup_noun, dm="filing their first form d",
        extra={"noun_mixed": _TECH_CO}),
    "startup_new_form_d": Duty(
        plural="filed new form ds with the sec for new private offerings",
        singular="filed a new form d with the sec for a new private offering",
        why=_RAISE_WHY,
        line="new sec form d for a new offering",
        short=("with a new sec form d", "with a new sec form d"),
        noun=_startup_noun, dm="filing new form ds",
        extra={"noun_mixed": _TECH_CO}),
})

# --- SBALoans (2026-11-04): SBA FOIA 7(a) / 504 approvals -----------------------------
# The record is an APPROVAL (some are not yet disbursed): never "funded". The lender
# is never named and neither is a person. SBA's servicing rules have the lender
# monitor the loan through periodic borrower financial statements (SOP 50 57), and
# a loan authorization sets the borrower's own reporting terms; the file does not
# show a given loan's terms, so the why-clause says "will likely owe", not "owes".
# No dollar figure, no date. The noun is the generic "business": NAICS niches ride
# the lead's own `niche` (see `_SOURCE_NICHES`), not the wording.
# 2026-11-05: no why. "will likely owe" read as a guess, and the record does
# not show the loan's terms; the fact ("$500k loan, dental") carries it.
_SBA_WHY = None

DUTIES.update({
    "sba_7a_loan_approved": Duty(
        plural="were approved for sba loans",
        singular="was approved for an sba loan",
        why=_SBA_WHY,
        line="approved for an sba loan",
        short=("approved for sba loans", "approved for an sba loan"),
        noun=("business", "businesses"), dm="getting approved for sba 7(a) loans"),
    "sba_504_loan_approved": Duty(
        plural="were approved for sba loans",
        singular="was approved for an sba loan",
        why=_SBA_WHY,
        line="approved for an sba loan",
        short=("approved for sba loans", "approved for an sba loan"),
        noun=("business", "businesses"), dm="getting approved for sba 504 loans"),
})

# --- Cannabis (Row 8c, 2026-10-30): state cannabis licensees ------------------------
# The predicate is only what the state's record shows. A "why" only where the
# license class collects the state cannabis tax (`collects_state_cannabis_tax`
# on EVERY lead). Never "280E": no list shows whether a business's product is
# medical (rescheduled) or adult-use. No dollar figures.
_CANNABIS = ("cannabis business", "cannabis businesses")
_CANNABIS_KIND = {"retail": "dispensary", "delivery": "delivery",
                  "microbusiness": "microbusiness", "cultivation": "cultivator",
                  "manufacturing": "processor", "distribution": "distributor",
                  "courier": "courier", "testing": "lab", "vertical": "dispensary"}


def _cannabis_kind(lead: Lead) -> str:
    return _CANNABIS_KIND.get(str(_payload(lead).get("license_kind") or ""), "")


def _cannabis_tax_why(leads: list[Lead]) -> tuple[str, str] | None:
    if leads and all(_payload(ld).get("collects_state_cannabis_tax") is True for ld in leads):
        return ("so each now has state cannabis tax returns to file",
                "so it now has state cannabis tax returns to file")
    return None


def _cannabis_opened(lead: Lead) -> str:
    return ("opened to the public"
            if _payload(lead).get("event_field") == "opened_to_public"
            else "was cleared by the state to start operating")


def _cannabis_opened_plural(leads: list[Lead]) -> str:
    if leads and all(_cannabis_opened(ld) == "opened to the public" for ld in leads):
        return "opened to the public"
    return "started operating under their state cannabis licenses"


DUTIES.update({
    "cannabis_new_license": Duty(
        plural="got new state cannabis licenses",
        singular="got a new state cannabis license",
        why=_cannabis_tax_why, detail=_cannabis_kind,
        line="new state cannabis license",
        short=("with new cannabis licenses", "with a new cannabis license"),
        noun=_CANNABIS, dm="getting new state cannabis licenses"),
    "cannabis_began_operations": Duty(
        plural=_cannabis_opened_plural, singular=_cannabis_opened,
        why=_cannabis_tax_why, detail=_cannabis_kind,
        line="just opened under a state cannabis license",
        short=("that just opened", "that just opened"),
        noun=_CANNABIS, dm="just opening under state cannabis licenses"),
    "cannabis_tax_report_violation": Duty(
        plural="were cited by the state's cannabis board for missing monthly tax "
               "reports or payments",
        singular="was cited by the state's cannabis board for missing monthly tax "
                 "reports or payments",
        line="cited for missing monthly cannabis tax reports",
        short=("cited over cannabis tax reports", "cited over cannabis tax reports"),
        noun=_CANNABIS, dm="cited over monthly cannabis tax reports"),
    "cannabis_recordkeeping_violation": Duty(
        plural="were cited by the state's cannabis board over their recordkeeping",
        singular="was cited by the state's cannabis board over its recordkeeping",
        line="cited by the state over recordkeeping",
        short=("cited over recordkeeping", "cited over recordkeeping"),
        noun=_CANNABIS, dm="cited over cannabis recordkeeping"),
    "cannabis_licensee_tax_delinquent": Duty(
        plural="are on the state's top 500 sales and use tax delinquent list",
        singular="is on the state's top 500 sales and use tax delinquent list",
        line="on california's top 500 tax delinquent list",
        short=("on the state's top 500 tax list", "on the state's top 500 tax list"),
        noun=_CANNABIS, dm="on california's top 500 tax delinquent list"),
})
# Held (2026-10-30): worded, not approved.
HELD_DUTIES.update({
    "cannabis_traceability_violation": Duty(
        plural="were cited by the state over their seed-to-sale inventory tracking",
        singular="was cited by the state over its seed-to-sale inventory tracking",
        line="cited over seed-to-sale inventory tracking",
        short=("cited over inventory tracking", "cited over inventory tracking"),
        noun=_CANNABIS, dm="cited over seed-to-sale inventory tracking"),
    "cannabis_license_suspended": Duty(
        plural="have suspended state cannabis licenses",
        singular="has a suspended state cannabis license",
        line="state cannabis license suspended",
        short=("with suspended cannabis licenses", "with a suspended cannabis license"),
        noun=_CANNABIS, dm="with suspended state cannabis licenses"),
})

# Funds (2026-10-30), HELD until the user approves it. The record: the
# adviser's latest Form ADV filing of any kind predates its last fiscal year
# end and the 90-day annual-amendment deadline (rules 204-1 / 204-4) has
# passed. "not on file", never "late" / "missed": extensions are not public.
HELD_DUTIES["adv_annual_amendment_overdue"] = Duty(
    plural="don't have their annual form adv update on file with the sec",
    singular="doesn't have its annual form adv update on file with the sec",
    detail=lambda ld: ("two years running"
                       if _payload(ld).get("missed_years") == 2 else ""),
    line="annual form adv update not on file",
    short=("without their form adv update", "without its form adv update"),
    noun=("fund manager", "fund managers"),
    dm="with no annual form adv update on file")

# ======================================================================================
# 2026-11-02: Restaurants, TexasPermits, Regulated, HomeServices, Community,
# Professional and the church 990-T types. Wording from each source's
# INVENTORY_HOOKUP.md / CHURCH_HOOKUP.md. The ENABLED types go in `DUTIES`, the
# HELD ones in `HELD_DUTIES` (worded, not used until approved: delete the type
# from `gift.engine._HELD` AND add it to the Inventory's APPROVED_SIGNALS).
# The Texas Railroad Commission types have no wording on purpose: the
# Inventory never ingests them (RRC terms allow noncommercial use only).
# ======================================================================================

def _title_if_shouted(name: str) -> str:
    return name.title() if name and name.isupper() else name


# --- Restaurants -------------------------------------------------------------------
# The record proves a LICENCE, not a business type, so no opener prints a noun
# (`bare`). Never "restaurant", never "company". No "why" on either wording:
# a restaurant that only added liquor would make "now files sales tax" untrue,
# and the record shows nothing about what a takeover changes in the books.
def _was(lead: Lead) -> str:
    """"was Himalayan Hub" when the record names the previous licensee at the
    premises (never a person: the source drops people's names, and a name that
    looks like one is left out here too)."""
    prior = _payload(lead).get("prior_licensee") or {}
    name = prior.get("trade_name") or prior.get("dba") or prior.get("legal_name") or ""
    name = _title_if_shouted(" ".join(str(name).split()))
    if not name or looks_like_person(name):
        return ""
    return f"was {name}"


_NEW_OWNER = Duty(
    plural="changed hands, each with its liquor license now in the new owner's name",
    singular="changed hands, with its liquor license now in the new owner's name",
    detail=_was,
    line="new owner, liquor license in its name",
    short=("under new owners", "under a new owner"), bare=True, dm="changing hands")
def _sales_tax_why(leads: list[Lead]) -> tuple[str, str] | None:
    """The sales tax returns the licence starts (the regulator's record names
    the duty: `filing_duty` sales_tax), when every lead is in one state."""
    from system_b.copy.subject import state_display as _sd

    states = {(ld.state or "").upper() for ld in leads}
    if len(states) != 1 or not all(_payload(ld).get("filing_duty") == "sales_tax" for ld in leads):
        return None
    st = _sd(next(iter(states)))
    if not st:
        return None
    return (f"so each now files {st} sales tax returns", f"so it now files {st} sales tax returns")


_NEW_LICENSE = Duty(
    plural="got new liquor licenses", singular="got a new liquor license",
    why=_sales_tax_why,
    line="new liquor license",
    short=("with new liquor licenses", "with a new liquor license"), bare=True,
    dm="getting new liquor licenses")

DUTIES.update({                        # ENABLED (hand checks 7% and 8% false positives)
    "liquor_license_new_owner_ca": _NEW_OWNER,
    "liquor_license_new_owner_tx": _NEW_OWNER,
    # Approved 2026-11-05 by the user. The 16-50% hand-check misses were "not a
    # new restaurant"; the wording claims only what the record proves: a new
    # licence ("got a new liquor license"), or a licence in a new owner's name.
    **{t: _NEW_LICENSE for t in ("liquor_license_new_tx", "liquor_license_new_ca",
                                 "liquor_license_new_ny", "liquor_license_new_fl",
                                 "liquor_license_new_co", "liquor_license_new_chicago")},
    **{t: _NEW_OWNER for t in ("liquor_license_new_owner_ny",
                               "liquor_license_new_owner_chicago")},
})
# 2026-11-06, approved by the user ("add lead types that are built and ready").
DUTIES.update({
    "tx_new_mixed_beverage_permit": Duty(
        plural="got new mixed beverage permits from the state",
        singular="got a new mixed beverage permit from the state",
        why=("so each now files monthly mixed beverage tax reports",
             "so it now files monthly mixed beverage tax reports"),
        line="new texas mixed beverage permit, monthly tax reports",
        short=("with new liquor permits", "with a new liquor permit"), bare=True,
        dm="getting new texas mixed beverage permits"),
})
HELD_DUTIES.update({                   # HELD (wording ready)
    "chicago_new_food_license": Duty(
        plural="got new city food licenses", singular="got a new city food license",
        line="new chicago food license",
        short=("with new food licenses", "with a new food license"), bare=True,
        dm="getting new city food licenses"),
})

# --- TexasPermits ------------------------------------------------------------------
# The record shows a permit date and the date the Comptroller lists the outlet as
# first liable for sales tax (the dataset's own definition of
# `outlet_first_sales_date`). Never "owe", "penalty" or "back taxes": sales through
# a marketplace are excluded from the seller's own report (Tax Code 151.0242(d)),
# so a late registrant may owe no tax, only the returns; and the $50-per-late-return
# rule would imply an assessment the record does not show. A test scans for them.
_TX_GROUP_NOUN = {
    "ecommerce": ("online seller", "online sellers"),
    "manufacturing": ("manufacturer", "manufacturers"),
    "food_beverage": ("food and beverage maker", "food and beverage makers"),
    "caterer": ("caterer", "caterers"),
    "farm": ("agriculture business", "agriculture businesses"),   # 111/112 + 115 support
}


def _tx_noun(lead: Lead) -> tuple[str, str] | None:
    """By the outlet's NAICS slice; None (the generic noun) for any other."""
    return _TX_GROUP_NOUN.get(str(_payload(lead).get("niche_group") or ""))


def _tx_late_months(lead: Lead) -> str:
    m = _payload(lead).get("months_first_sale_to_permit")
    return f"{m} months late" if isinstance(m, int) and m > 1 else ""


def _brewer_noun(lead: Lead) -> tuple[str, str]:
    return ("brewpub", "brewpubs") if _payload(lead).get("brewpub") \
        else ("brewery", "breweries")


DUTIES.update({
    "tx_late_sales_tax_registration": Duty(
        plural="got texas sales tax permits months after their first taxable sales",
        singular="got a texas sales tax permit months after its first taxable sale",
        why=("so each has earlier returns to cover", "so it has earlier returns to cover"),
        detail=_tx_late_months,
        line="got a sales tax permit months late",
        short=("registered late for sales tax", "registered late for sales tax"),
        noun=_tx_noun, dm="registering late for texas sales tax"),
    "tx_new_sales_tax_permit": Duty(
        plural="got new texas sales tax permits",
        singular="got a new texas sales tax permit",
        why=("so each now files sales tax returns", "so it now files sales tax returns"),
        line="new texas sales tax permit, returns start",
        short=("with new sales tax permits", "with a new sales tax permit"),
        noun=_tx_noun, dm="getting new texas sales tax permits"),
})
HELD_DUTIES.update({
    "tx_new_brewer_license": Duty(
        plural="got new brewer's licenses from the state",
        singular="got a new brewer's license from the state",
        why=("so each now files federal beer excise returns",
             "so it now files federal beer excise returns"),
        line="new texas brewer's license, federal excise returns start",
        short=("with new brewer's licenses", "with a new brewer's license"),
        noun=_brewer_noun, dm="getting new texas brewer's licenses"),
})

# --- Regulated (Florida OFR; out-of-state licensees kept) -----------------------------
# Only duties verified in rule text appear in a "why" (Inventory/Regulated hookup, 8).
# No dollar figure; no "audit" for mortgage lenders (Florida has no annual audit duty
# for them after licensing); no noun: the licence is in the predicate already
# ("these 3 mortgage lenders ... got new florida mortgage lender licenses" said it
# twice), and the place is each lead's own HQ state, so a Florida licence held by a
# California firm reads "these 3 companies in california got new florida ...".
DUTIES.update({
    "fl_new_money_transmitter": Duty(
        plural="got new florida money transmitter licenses",
        singular="got a new florida money transmitter license",
        why=("so each files audited statements yearly and reports quarterly",
             "so it files audited statements yearly and reports quarterly"),
        line="new florida money transmitter license, yearly audit",
        short=("with money transmitter licenses", "with a money transmitter license"),
        dm="getting new florida money transmitter licenses"),
    "fl_new_mortgage_lender": Duty(
        plural="got new florida mortgage lender licenses",
        singular="got a new florida mortgage lender license",
        why=("so each reports quarterly and must keep a net worth",
             "so it reports quarterly and must keep a net worth"),
        line="new florida mortgage lender license",
        short=("with new lender licenses", "with a new lender license"),
        dm="getting new florida mortgage lender licenses"),
    "fl_new_consumer_finance_lender": Duty(
        plural="got new florida consumer finance licenses",
        singular="got a new florida consumer finance license",
        why=("so each files an annual report with the state",
             "so it files an annual report with the state"),
        line="new florida consumer finance license",
        short=("with consumer finance licenses", "with a consumer finance license"),
        dm="getting new florida consumer finance licenses"),
})
_OPERATOR = ("oil and gas operator", "oil and gas operators")
HELD_DUTIES.update({
    "nm_ocd_new_operator": Duty(
        plural="registered with new mexico's oil conservation division as new well operators",
        singular="registered with new mexico's oil conservation division as a new well operator",
        why=("so each now files a monthly production report (form c-115) for every well",
             "so it now files a monthly production report (form c-115) for every well"),
        line="new new mexico well operator",
        short=("new nm well operators", "a new nm well operator"),
        noun=_OPERATOR, dm="registering as new new mexico well operators"),
    "fcc_499a_missed": Duty(
        plural="have no fcc form 499-a on file for this year (due april 1)",
        singular="has no fcc form 499-a on file for this year (due april 1)",
        line="fcc form 499-a not filed this year",
        short=("missing this year's form 499-a", "missing this year's form 499-a"),
        noun=("telecom provider", "telecom providers"),
        dm="missing this year's fcc form 499-a"),
    "fcc_499_new_registrant": Duty(
        plural="registered with the fcc as new telecom providers",
        singular="registered with the fcc as a new telecom provider",
        why=("so each now files an fcc form 499-a revenue report every april 1",
             "so it now files an fcc form 499-a revenue report every april 1"),
        line="new fcc 499 registrant",
        short=("new telecom providers", "a new telecom provider"),
        noun=("telecom provider", "telecom providers"),
        dm="registering as new telecom providers"),
})

# --- HomeServices -----------------------------------------------------------------
# "Accepted", never "approved" / "certified" (the feed is the Notice of Acceptance
# list); the why is "has agreed to" (20 CFR 655.20), never "now owes"; "or post a
# bond" always rides with the Virginia net-worth claim; no "$1 million" on Class A.
_H2B_NOUN = {
    "landscaping": ("landscaper", "landscapers"),
    "hvac_plumbing_electrical": ("trades company", "trades companies"),
    "cleaning_janitorial": ("cleaning company", "cleaning companies"),
    "pest_control": ("pest control company", "pest control companies"),
    "pool_services": ("pool company", "pool companies"),
    "security_services": ("security company", "security companies"),
    # No "contractors", "builders", "hotels" or "restaurants": an H-2B application
    # carries an occupation and a NAICS code, not a business type (the hookup's own
    # residual risk: first-timers named "Ale Trucks" and "Arcol Consulting" filed as
    # construction laborers). Those read "seasonal employers".
}


def _seasonal_noun(lead: Lead) -> tuple[str, str]:
    """By the lead's own niche; anything else is a 'seasonal employer'."""
    return _H2B_NOUN.get(lead.niche or "", ("seasonal employer", "seasonal employers"))


def _va_noun(lead: Lead) -> tuple[str, str]:
    n = lead.niche or ""
    if n == "hvac_plumbing_electrical":
        return ("trades contractor", "trades contractors")
    if n == "landscaping":
        return ("landscaping contractor", "landscaping contractors")
    if n == "pool_services":
        return ("pool contractor", "pool contractors")
    return ("contractor", "contractors")


_H2B_WHY = ("so each agreed to prevailing wage and pay-record rules",
            "so it agreed to prevailing wage and pay-record rules")
# The hookup's figures ($45,000 / $15,000 of net worth) are left out: no sent text
# carries a dollar figure (the amounts are in the insight and the payload).
_VA_A_WHY = ("so each had to prove its net worth to virginia",
             "so it had to prove its net worth to virginia")
_VA_B_WHY = _VA_A_WHY

DUTIES.update({
    "h2b_first_time_employer": Duty(
        plural="had their first H-2B applications accepted by the labor dept",
        singular="had its first H-2B application accepted by the labor dept",
        why=_H2B_WHY,
        line="first H-2B application, accepted by labor dept",
        short=("with first H-2B applications", "with a first H-2B application"),
        noun=_seasonal_noun, dm="filing their first H-2B seasonal worker applications"),
    "h2b_seasonal_employer": Duty(
        plural="had H-2B applications accepted by the labor dept",
        singular="had an H-2B application accepted by the labor dept",
        why=_H2B_WHY,
        line="H-2B application accepted by labor dept",
        short=("with H-2B worker applications", "with an H-2B worker application"),
        noun=_seasonal_noun, dm="filing H-2B seasonal worker applications"),
    "va_new_class_a_contractor": Duty(
        plural="got new virginia class A licenses",
        singular="got a new virginia class A license",
        why=_VA_A_WHY,
        line="new virginia class A contractor license",
        short=("with new class A licenses", "with a new class A license"),
        noun=_va_noun, dm="getting new virginia class A contractor licenses"),
})
HELD_DUTIES.update({
    "h2b_seasonal_employer_other_industry": Duty(
        plural="had H-2B applications accepted by the labor dept",
        singular="had an H-2B application accepted by the labor dept",
        why=_H2B_WHY,
        line="H-2B application accepted by labor dept",
        short=("with H-2B worker applications", "with an H-2B worker application"),
        noun=_seasonal_noun, dm="filing H-2B seasonal worker applications"),
    "va_new_class_b_contractor": Duty(
        plural="got new virginia class B licenses",
        singular="got a new virginia class B license",
        why=_VA_B_WHY,
        line="new virginia class B contractor license",
        short=("with new class B licenses", "with a new class B license"),
        noun=_va_noun, dm="getting new virginia class B contractor licenses"),
    "va_contractor_upgraded_class_a": Duty(
        plural="moved up to virginia class A contractor licenses",
        singular="moved up to a virginia class A contractor license",
        why=_VA_A_WHY,
        line="moved up to a virginia class A contractor license",
        short=("moving up to class A licenses", "moving up to a class A license"),
        noun=_va_noun, dm="moving up to virginia class A contractor licenses"),
})

# --- Community --------------------------------------------------------------------
# The predicate is only what the record shows; a "why" only where the statute text
# was read; no dollar figure in the opener; never "new business", "sworn
# statement", "single audit", "failed" or "missing". Display names (VA and
# USAspending print upper case) are title-cased by the inventory client.
# One name per email: a management company's inbox can be the contact on several
# VA associations, and franchisees share brand names (HOTWORX): a gift lists each
# `name` once (`gift.engine._same_company`).
# The three gym registries say "fitness business", not "gym": Florida's health
# studios include Pilates, yoga and martial arts, and the record does not say which.
_FITNESS = ("fitness business", "fitness businesses")
_SPONSOR = ("child care program", "child care programs")
_ASSN = ("community association", "community associations")
_CONG = ("congregation", "congregations")
_SCHOOL = ("career school", "career schools")

DUTIES.update({
    "tx_health_spa_new": Duty(       # Occ. Code 702.101, 702.151, 702.201-.202
        plural="just registered as texas health spas",
        singular="just registered as a texas health spa",
        line="new texas health spa registration",
        short=("just registered as health spas", "just registered as a health spa"),
        noun=_FITNESS, dm="just registering as health spas in texas"),
    "fl_health_studio_new": Duty(    # Fla. Stat. 501.015(1)-(2), 501.016(1)-(2), (5)
        plural="just registered as florida health studios",
        singular="just registered as a florida health studio",
        why=("so each needs a bond or exemption, renewed yearly",
             "so it needs a bond or exemption, renewed yearly"),
        line="new florida health studio registration",
        short=("just registered as health studios", "just registered as a health studio"),
        noun=_FITNESS, dm="just registering as health studios in florida"),
    "ct_health_club_new": Duty(      # Conn. Gen. Stat. 21a-223(a), 21a-226(b)
        plural="just got connecticut health club licenses",
        singular="just got a connecticut health club license",
        why=("so each renews yearly and pays into a state fund",
             "so it renews yearly and pays into a state fund"),
        line="new connecticut health club license",
        short=("with new club licenses", "with a new club license"),
        noun=_FITNESS, dm="just getting connecticut health club licenses"),
    "tx_cacfp_new_sponsor": Duty(    # 7 CFR 226.10(c)-(d), 226.15(e)
        plural="were just approved to run the federal child care food program",
        singular="was just approved to run the federal child care food program",
        why=("so each now files monthly meal reimbursement claims",
             "so it now files monthly meal reimbursement claims"),
        line="new federal child care food program sponsor",
        short=("approved for the food program", "approved for the food program"),
        noun=_SPONSOR, dm="just approved for the federal child care food program"),
    "va_hoa_new_registration": Duty( # Va. Code 55.1-1835; 18VAC48-60-15
        plural="just registered with virginia's common interest community board",
        singular="just registered with virginia's common interest community board",
        why=("so each files an annual report and fee every year",
             "so it files an annual report and fee every year"),
        line="new virginia hoa / condo association registration",
        short=("with new state registrations", "with a new state registration"),
        noun=_ASSN, dm="just registering with virginia's cic board"),
    "nsgp_security_grant_subaward": Duty(  # 2 CFR 200.302, 200.318, 200.334
        plural="recently received FEMA security grants",
        singular="recently received a FEMA security grant",
        why=("so each must account for the grant by federal rules",
             "so it must account for the grant by federal rules"),
        line="fema nonprofit security grant subaward",
        short=("with FEMA security grants", "with a FEMA security grant"),
        noun=_CONG, org=True, dm="receiving fema nonprofit security grants"),
})
HELD_DUTIES.update({
    "ct_health_club_lapsed": Duty(
        plural="let their state health club licenses lapse on 9/30",
        singular="let its state health club license lapse on 9/30",
        line="connecticut health club license lapsed",
        short=("with lapsed club licenses", "with a lapsed club license"),
        noun=_FITNESS, dm="with lapsed connecticut health club licenses"),
    "tx_career_school_fs_penalty": Duty(     # 40 TAC 807.35
        plural="were fined by the state for turning in their yearly career school "
               "financial statements late",
        singular="was fined by the state for turning in its yearly career school "
                 "financial statements late",
        line="texas career school fined over late financial statements",
        short=("fined over late statements", "fined over late statements"),
        noun=_SCHOOL, dm="fined over late career school financial statements"),
    "tx_career_school_new": Duty(            # 40 TAC 807.35
        plural="just got licensed as career schools",
        singular="just got licensed as a career school",
        why=("so each now owes the state yearly financial statements, the first ones "
             "audited or compiled by a CPA",
             "so it now owes the state yearly financial statements, the first ones "
             "audited or compiled by a CPA"),
        line="new texas career school",
        short=("newly licensed schools", "a newly licensed school"),
        noun=_SCHOOL, dm="just licensed as texas career schools"),
    "ca_bppe_annual_report_missing": Duty(   # 5 CCR 74110, 74115
        plural="have no 2024 annual report on the state school bureau's list; it was due "
               "in december and includes GAAP financial statements",
        singular="has no 2024 annual report on the state school bureau's list; it was due "
                 "in december and includes GAAP financial statements",
        line="california school with no annual report on file",
        short=("with no annual report on file", "with no annual report on file"),
        noun=_SCHOOL, dm="with no annual report on california's list"),
    "ca_bppe_first_annual_report": Duty(
        plural="filed their first annual report with the state school bureau",
        singular="filed its first annual report with the state school bureau",
        why=("so each now owes GAAP financial statements every year",
             "so it now owes GAAP financial statements every year"),
        line="california school's first annual report",
        short=("with a first annual report", "with a first annual report"),
        noun=_SCHOOL, dm="filing first annual reports in california"),
    "va_hoa_registration_lapsed": Duty(      # 18VAC48-60-17 D
        plural="dropped off the state's association registration list more than a year "
               "after it expired",
        singular="dropped off the state's association registration list more than a year "
                 "after it expired",
        line="virginia association registration lapsed over 12 months",
        short=("with lapsed registrations", "with a lapsed registration"),
        noun=_ASSN, dm="with lapsed virginia association registrations"),
})

# --- Professional -----------------------------------------------------------------
# The predicate is only what the record shows; a "why" only where a statute or
# regulator text ties a duty to that record. Never "can't practice",
# "noncompliant" or "must open an escrow account" (none is proven by the record).
# One name per email: a TX PEO and the same company's FL employee leasing licence
# are two leads of two types (PLG PEO LLC): a gift lists a `name` once.
_CPA_FIRMS = ("cpa firm", "cpa firms")
_LAWYERS = ("lawyer", "lawyers")
_PEOS = ("peo", "peos")
_VENDORS = ("tech vendor", "tech vendors")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def _month_day(iso: str) -> str:
    """"2026-12-13" -> "dec 13"; "" when it is not a date."""
    try:
        y, m, d = (int(x) for x in iso[:10].split("-"))
        return f"{_MONTHS[m - 1]} {d}"
    except (ValueError, IndexError):
        return ""


def _bar_detail(lead: Lead) -> str:
    p = _payload(lead)
    return "quarterly cpa trust reports required" if p.get("cpa_condition") else \
        (p.get("sanction") or "")


def _peo_expiry(lead: Lead) -> str:          # "expires dec 13"
    d = _month_day(str(_payload(lead).get("expiration_date") or ""))
    return f"expires {d}" if d else ""


def _cpeo_list(leads: list[Lead]) -> str:
    kinds = {_payload(ld).get("list") for ld in leads}
    word = "revoked" if kinds == {"revoked"} else "suspended" if kinds == {"suspended"} \
        else "revoked or suspended"
    return f"are on the irs's list of {word} certified peos"


DUTIES.update({
    "cpa_firm_license_delinquent": Duty(
        plural="have firm licenses their state board of accountancy lists as delinquent",
        singular="has a firm license its state board of accountancy lists as delinquent",
        line="firm license listed as delinquent",
        short=("with delinquent firm licenses", "with a delinquent firm license"),
        noun=_CPA_FIRMS, dm="with firm licenses their state board lists as delinquent"),
    "cpa_firm_license_expired": Duty(
        plural="had their washington cpa firm licenses expire",
        singular="had its washington cpa firm license expire",
        line="washington cpa firm license expired",
        short=("with expired firm licenses", "with an expired firm license"),
        noun=_CPA_FIRMS, dm="whose washington cpa firm licenses expired"),
    "ny_new_cpa_firm": Duty(
        plural="registered as new cpa firms with new york state",
        singular="registered as a new cpa firm with new york state",
        line="new cpa firm registered in new york",
        short=("just registered as cpa firms", "just registered as a cpa firm"),
        dm="registering as new cpa firms"),
    "ny_new_law_firm": Duty(
        plural="registered as new law firms with new york state",
        singular="registered as a new law firm with new york state",
        line="new law firm registered in new york",
        short=("just registered as law firms", "just registered as a law firm"),
        dm="registering as new law firms"),
    "fl_bar_trust_account_discipline": Duty(
        plural="were disciplined by the florida supreme court over trust-account rules",
        singular="was disciplined by the florida supreme court over trust-account rules",
        detail=_bar_detail,
        line="disciplined over trust-account rules",
        short=("disciplined over trust accounts", "disciplined over trust accounts"),
        noun=_LAWYERS, dm="disciplined over trust-account rules"),
    "tx_peo_license_renewal_due": Duty(
        plural="have texas peo licenses up for renewal in the next three months",
        singular="has a texas peo license up for renewal in the next three months",
        why=("and each renewal needs cpa-audited statements",
             "and the renewal needs cpa-audited statements"),
        detail=_peo_expiry,
        line="texas peo license renewal due, audited statements",
        short=("with peo license renewals due", "with a peo license renewal due"),
        noun=_PEOS, dm="with texas peo license renewals coming up"),
    "fl_employee_leasing_new_license": Duty(
        plural="got new florida employee leasing licenses",
        singular="got a new florida employee leasing license",
        why=("so each files cpa-audited statements every year",
             "so it files cpa-audited statements every year"),
        line="new florida employee leasing license",
        short=("with employee leasing licenses", "with an employee leasing license"),
        noun=_PEOS, dm="getting new florida employee leasing licenses"),
    "cpeo_newly_certified": Duty(
        plural="were newly certified by the irs as peos",
        singular="was newly certified by the irs as a peo",
        why=("so each files cpa-audited statements and cpa-examined quarterly reports",
             "so it files cpa-audited statements and cpa-examined quarterly reports"),
        line="newly irs-certified peo",
        short=("newly irs-certified", "newly irs-certified"),
        noun=_PEOS, dm="newly certified by the irs"),
    "tx_dir_first_contract": Duty(
        plural="got their first texas dir technology contracts",
        singular="got its first texas dir technology contract",
        why=("so each files a monthly sales report with the state",
             "so it files a monthly sales report with the state"),
        line="first texas dir contract, monthly sales reports",
        short=("with first state tech contracts", "with a first state tech contract"),
        noun=_VENDORS, dm="getting first texas dir contracts"),
})
HELD_DUTIES.update({
    "tx_peo_new_license": Duty(
        plural="got new texas peo licenses this year",
        singular="got a new texas peo license this year",
        why=("so each renewal needs cpa-audited financial statements",
             "so its renewal needs cpa-audited financial statements"),
        line="new texas peo license",
        short=("with new peo licenses", "with a new peo license"),
        noun=_PEOS, dm="getting new texas peo licenses"),
    "cpeo_revoked_or_suspended": Duty(
        plural=_cpeo_list,
        singular=lambda ld: _cpeo_list([ld]).replace("are on", "is on"),
        line="on the irs revoked / suspended cpeo list",
        short=("off the irs's cpeo list", "off the irs's cpeo list"),
        noun=_PEOS, dm="on the irs's revoked or suspended cpeo lists"),
})

# --- Churches / religious organizations: Form 990-T (Nonprofit CHURCH_HOOKUP.md) ----
# Churches file no Form 990, but the 990-T (business income) is the one federal
# return they do file. "Side income" is the return's unrelated business income;
# never "owes", "late", "failed", or a dollar figure in the opener (the figures
# are in `evidence_text` for the click-through).
_CHURCH = ("church", "churches")
_FAITH_ORG = ("faith-based organization", "faith-based organizations")


def _church_noun(lead: Lead) -> tuple[str, str]:
    """"churches" only when the IRS codes the filer a church (BMF foundation code
    10); any other religious filer is a "faith-based organization". A gift that
    mixes the two falls back to `noun_mixed`."""
    return _CHURCH if _payload(lead).get("religious_basis") == "church" else _FAITH_ORG


_ENTITY_WORD = re.compile(r"\b(?:llc|l\.l\.c|inc|corp|corporation|ltd|llp|lp|pllc|trust|"
                          r"foundation|ministries|church)\b|,")


def _church_990t_detail(lead: Lead) -> str:      # "(parking lot rental, fy2025)"
    """The trade in the filer's words; some filers type the NAME of the business
    that earns the income ("imagine enterprises, llc"), which says nothing about
    the trade and is left out."""
    p = _payload(lead)
    act = " ".join(str(p.get("activity") or "").lower().split())
    if _ENTITY_WORD.search(act):
        act = ""
    return act if 0 < len(act) <= 40 else ""


DUTIES.update({
    "church_990t_first": Duty(
        plural="filed their first form 990-t (business-income tax return)",
        singular="filed its first form 990-t (business-income tax return)",
        why=("so each owes one whenever side income passes the limit",
             "so it owes one whenever side income passes the limit"),
        detail=_church_990t_detail,
        line="first form 990-t (business-income tax return)",
        short=("filing their first 990-ts", "filing its first 990-t"),
        noun=_church_noun, org=True, extra={"noun_mixed": _FAITH_ORG},
        dm="filing their first business-income tax returns"),
    "church_990t_no_preparer": Duty(
        plural="filed their own form 990-t with no paid preparer listed",
        singular="filed its own form 990-t with no paid preparer listed",
        # The record shows one return with no paid preparer, not a habit: the
        # "why" states only the verified duty (Treas. Reg. 1.6012-2(e)).
        why=("so each owes one whenever side income passes the limit",
             "so it owes one whenever side income passes the limit"),
        detail=_church_990t_detail,
        line="filed its own 990-t, no paid preparer listed",
        short=("filing their own 990-ts", "filing its own 990-t"),
        noun=_church_noun, org=True, extra={"noun_mixed": _FAITH_ORG},
        dm="filing their own 990-t business-income tax returns"),
})


# --- Healthcare: new practices (NPPES weekly files + NPI Registry, 2026-11-02) ---------
# `new_practice_npi`: a practice whose FIRST organization NPI was issued in the last
# 90 days; `new_practice_medicare_enrollment`: the same, and CMS approved a Medicare
# organization enrollment in the window. The NPI opener is RECORD-ONLY (user): it says
# what the registry shows and nothing about billing ("so each is new to billing
# insurance" was an inference). Never "opened" / "just started": ~5% are established
# clinicians' new entities. The Medicare one keeps its clause: an approved group
# enrollment is what lets it bill Medicare as a group. The noun is the practice kind
# (`provider_type`); a mixed gift says "practices".
_PRACTICE_NOUN = {
    "medical": ("medical practice", "medical practices"),
    "dental": ("dental practice", "dental practices"),
    "therapy": ("therapy practice", "therapy practices"),
    "chiropractic": ("chiropractic practice", "chiropractic practices"),
    "optometry": ("optometry practice", "optometry practices"),
    "behavioral": ("behavioral health practice", "behavioral health practices"),
}
_PRACTICES = ("practice", "practices")


def _practice_noun(lead: Lead) -> tuple[str, str]:
    return _PRACTICE_NOUN.get(str(_payload(lead).get("provider_type") or ""), _PRACTICES)


DUTIES.update({
    "new_practice_npi": Duty(
        plural="registered with the federal npi registry as new organizations",
        singular="registered with the federal npi registry as a new organization",
        line="new practice entity, first organization npi",
        short=("with new npi registrations", "with a new npi registration"),
        noun=_practice_noun, extra={"noun_mixed": _PRACTICES},
        dm="setting up new practice entities"),
    "new_practice_medicare_enrollment": Duty(
        plural="enrolled in medicare as new group practices",
        singular="enrolled in medicare as a new group practice",
        why=("so each now bills medicare under its own group number",
             "so it now bills medicare under its own group number"),
        line="new practice, newly enrolled in medicare",
        short=("newly enrolled in medicare", "newly enrolled in medicare"),
        noun=_practice_noun, extra={"noun_mixed": _PRACTICES},
        dm="opening new practices that bill medicare"),
})

# Every type above is approved (2026-10-30); `gift.engine.HELD_TYPES` still
# names any type whose wording is written but not yet approved.
DUTIES.update({t: d for t, d in HELD_DUTIES.items() if t not in HELD_TYPES})

# The FL Bar trust-account leads are individual lawyers (2026-11-02): held,
# because a gift never names a person. Its wording stays ready.
HELD_DUTIES["fl_bar_trust_account_discipline"] = DUTIES.pop("fl_bar_trust_account_discipline")

# --- Expanding businesses (2026-11-05, approved by the user) -------------------
# A company formed in one state that registered to do business in another
# (Colorado / Connecticut Secretary of State). What the filing shows, nothing
# more: where it registered and what it is ("a delaware llc"). Many are local
# businesses formed in Delaware or Wyoming; the words hold for both.
def _state_name(code: str | None) -> str:
    from system_b.gift.engine import _US_STATES

    names = {v: k for k, v in _US_STATES.items()}
    return names.get((code or "").strip().lower(), "")


def _registered_in(leads: list[Lead]) -> str:
    states = {_state_name(_payload(ld).get("state")) for ld in leads}
    # "from other states": each line prints the company's home city, so
    # "these 3 registered to do business in connecticut" over three Colorado
    # and Florida towns read as a contradiction (2026-11-12).
    if len(states) != 1 or not next(iter(states)):
        return "registered to do business in a new state"
    where = next(iter(states))
    # "from other states" only when every lead's own address is outside the
    # state it registered in: a Boulder company incorporated in Delaware is not
    # from another state (2026-11-12).
    if not all(ld.state and _state_name(ld.state) != where for ld in leads):
        return f"registered to do business in {where}"
    who = "from another state" if len(leads) == 1 else "from other states"
    return f"{who} registered to do business in {where}"


def _home(lead: Lead) -> str:
    p = _payload(lead)
    home = _state_name(p.get("home_jurisdiction"))
    kind = {"llc": "llc", "corporation": "corporation"}.get(
        str(p.get("entity_kind") or "").strip().lower(), "")
    if not (home and kind):
        return ""
    return f"{'an' if home[0] in 'aeiou' else 'a'} {home} {kind}"


# 2026-11-05 the user: held again. On its own a registration shows no need.
# 2026-11-06 approved ("add lead types that are built and ready"): it says
# only where it registered and what it is; no why.
DUTIES["new_business_expanding"] = Duty(
    plural=_registered_in,
    singular=lambda ld: _registered_in([ld]),
    line=lambda ld: _registered_in([ld]).removeprefix("from another state ").removeprefix(
        "from other states "),
    detail=_home,
    short=("newly registered in the state", "newly registered in the state"),
    bare=True, dm="registering to do business in a new state")


# --- New growth sources (2026-11-05; the user: "I trust you with the email
# wording"). Each states only what its record shows. -----------------------
def _fda_kind(leads: list[Lead]) -> str:
    kinds = {str(_payload(ld).get("submission") or "").lower() for ld in leads}
    if kinds == {"de novo"}:
        return "fda de novo grants" if len(leads) > 1 else "an fda de novo grant"
    return "fda clearances" if len(leads) > 1 else "an fda clearance"


def _fda_first(leads: list[Lead]) -> str:
    k = _fda_kind(leads)
    return f"got their first {k} for a medical device" if len(leads) > 1 \
        else f"got its first {k.removeprefix('an ')} for a medical device"


_SELL_DEVICE = ("so each can now sell that device in the us",
                "so it can now sell that device in the us")

DUTIES.update({
    # Healthcare (openFDA 510(k) / De Novo): a small US applicant.
    "fda_first_device_clearance": Duty(
        plural=_fda_first, singular=lambda ld: _fda_first([ld]),
        line="first fda clearance for a medical device",
        short=("with a first fda clearance", "with a first fda clearance"),
        why=_SELL_DEVICE, noun=("medical device company", "medical device companies"),
        dm="getting their first fda device clearance"),
    "fda_device_clearance": Duty(
        plural=lambda leads: f"got new {_fda_kind(leads)} for medical devices",
        singular=lambda ld: f"got {_fda_kind([ld])} for a new medical device",
        line="new fda clearance for a medical device",
        short=("with new fda clearances", "with a new fda clearance"),
        why=_SELL_DEVICE, noun=("medical device company", "medical device companies"),
        dm="getting fda device clearances"),
    # Construction (city open data): the contractor named on the permit.
    "construction_large_permit": Duty(
        plural="were named on new city building permits for large jobs",
        singular="was named as the contractor on a new city building permit for a large job",
        line="contractor on a new large city building permit",
        short=("on new large building permits", "on a new large building permit"),
        detail=lambda ld: (f"{_payload(ld).get('permits_in_window')} permits"
                           if str(_payload(ld).get("permits_in_window") or "1") not in ("0", "1")
                           else ""),
        noun=("contractor", "contractors"), dm="pulling large city building permits"),
    # Federal (SAM.gov monthly extract): a small business, new to SAM.
    "sam_new_entity_registration": Duty(
        plural="just registered as federal contractors",
        singular="just registered as a federal contractor",
        line="newly registered federal contractor",
        short=("new to federal contracting", "new to federal contracting"),
        dm="registering as federal contractors"),
    # Federal (NIH RePORTER / NSF / SBIR.gov): the firm's first SBIR/STTR award.
    "sbir_phase1_award": Duty(
        plural="won their first federal sbir research awards",
        singular="won its first federal sbir research award",
        why=_GRANT_RULES,
        line="first federal sbir research award",
        short=("with first sbir awards", "with a first sbir award"),
        dm="winning their first sbir award"),
})

DUTY_SIGNALS = frozenset(DUTIES)


def duty_for(lead: Lead) -> Duty | None:
    return DUTIES.get(lead.signal_type or "")


def shared_noun(leads: list[Lead], n: int) -> str | None:
    """The leads' own noun when every one shares it, else None."""
    nouns = {DUTIES[ld.signal_type].noun_for(ld) if ld.signal_type in DUTIES else None
             for ld in leads}
    if len(nouns) == 1:
        noun = next(iter(nouns))
        if noun:
            return noun[0] if n == 1 else noun[1]
    # A type whose noun differs lead by lead (Startups: "tech startups" only
    # when every one is young) names its shared fallback instead.
    falls = {DUTIES[ld.signal_type].extra.get("noun_mixed") if ld.signal_type in DUTIES
             else None for ld in leads}
    if len(falls) == 1:
        fall = next(iter(falls))
        if fall:
            return fall[0] if n == 1 else fall[1]
    return None


def bare_gift(leads: list[Lead]) -> bool:
    """Every lead's duty prints no business noun (Restaurants: the record proves a
    licence, not what the business is)."""
    return bool(leads) and all(ld.signal_type in DUTIES and DUTIES[ld.signal_type].bare
                               for ld in leads)


def all_organizations(leads: list[Lead]) -> bool:
    """Every lead is an organization rather than a company (the engineer line)."""
    return bool(leads) and all(ld.signal_type in DUTIES and DUTIES[ld.signal_type].org
                               for ld in leads)
