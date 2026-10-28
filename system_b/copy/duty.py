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

Every claim is the record's own words: "reported ... on its latest form
5500" (a Yes can be carried over a year), "doesn't have ... on edgar yet"
(never "is delinquent"), "were listed by their state as late" (never
"broke the law"). No dollar figure, no date beyond a form's year, no em dash.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

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
        return why[1] if len(leads) == 1 else why[0]

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

_AUDIT_WHY = ("and each has to show it's fixed in its next audit",
              "and it has to show it's fixed in its next audit")
_GRANT_RULES = ("so each now has strict tracking and reporting rules to follow",
                "so it now has strict tracking and reporting rules to follow")


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
        plural="have retirement plans past 120 account holders on their latest form 5500",
        singular="has a retirement plan past 120 account holders on its latest form 5500",
        why=("so each needs its first plan audit", "so it needs its first plan audit"),
        line="plan passed 120 account holders, first audit due",
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
        short=("that bought hud-assisted housing", "that bought hud-assisted housing"),
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
        plural="are nearing the size where ncua requires a full financial statement audit",
        singular="is nearing the size where ncua requires a full financial statement audit",
        line="nearing the size that needs a full audit",
        short=("nearing the full-audit line", "nearing the full-audit line"),
        noun=_CU, org=True, dm="nearing the size that needs a full audit"),
    "cu_over_500m_no_fs_audit": Duty(
        plural="passed the size where ncua requires a full audit, and their last one wasn't",
        singular="passed the size where ncua requires a full audit, and its last one wasn't",
        line="past the full-audit line, last audit wasn't one",
        short=("past the full-audit line", "past the full-audit line"),
        noun=_CU, org=True, dm="past the size that needs a full audit"),
    "cu_stale_audit": Duty(
        plural="list a last audit over two years old on their ncua call reports",
        singular="lists a last audit over two years old on its ncua call report",
        why=("and the rules require one every year", "and the rules require one every year"),
        line="last audit over two years old, per ncua",
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
        why=("so each must pay out student aid from its own cash first",
             "so it must pay out student aid from its own cash first"),
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
        why=("so each now owes the state an independent audit every year",
             "so it now owes the state an independent audit every year"),
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
        why=("so each needs a cpa report to get its credit certificate",
             "so it needs a cpa report to get its credit certificate"),
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
        plural="filed their first prevailing wage intents with the state",
        singular="filed its first prevailing wage intent with the state",
        why=("so each owes a wage affidavit when the job is done",
             "so it owes a wage affidavit when the job is done"),
        line="first washington prevailing wage job on record",
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
    return None


def all_organizations(leads: list[Lead]) -> bool:
    """Every lead is an organization rather than a company (the engineer line)."""
    return bool(leads) and all(ld.signal_type in DUTIES and DUTIES[ld.signal_type].org
                               for ld in leads)
