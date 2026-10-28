"""Step 5 — Email #1. EVERY part is deterministic code, including each
per-lead line (hiring, breach, funding are all templated). No model writes
any part of a sent email.

5a framing table, 5b left-field rotation, 5c CTA table, 5d template fill,
5e honesty enforcement (dates, dollar amounts, flags).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from system_b.copy.duty import DUTIES, DUTY_SIGNALS, all_organizations
from system_b.copy.honesty import date_suffix, is_raise, strip_dollar_amounts, strip_em_dashes
from system_b.copy.lex import (
    city_display,
    fix_articles,
    niche_display,
    niche_noun,
    revenue_display,
    spoken_name,
    state_display,
)
from system_b.copy.subject import build_subject, lead_noun, niche_claim
from system_b.gift.engine import compute_match_level, licensing_state
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead
from system_b.niches.base import default_pack

# Retired 2026-08-04: this fired on 21 of 23 prospects, so it drowned the flags
# that actually needed a decision. `config.MAX_JOB_LEAD_AGE_DAYS` now bounds
# posting staleness in code instead. Kept as a named constant only so a pack
# that wants an explicit "check this one" flag has a template to copy.
CFO_PRIORITY_FLAG = (
    "job_fractional_cfo / low-confidence lead present — google the posting and "
    "confirm it's still live before sending (no date in copy)"
)

# 5b — the left-field line. ONE line, shared by every pack, with the audience as
# its only variable.
#
# It used to be per-pack, and the packs drifted: cfo opened "i'm an engineer"
# while accounting and bookkeeping opened "most bookkeepers i talk to". The
# engineer reveal is the strongest thing in the email — it is what stops a
# machine-built gift from reading as spray-and-pray — so every buyer gets it.
# Nothing about it is CFO-specific.
#
# Four jobs in 24 words, which is why the wording is load-bearing:
#   "i'm an engineer"        — credibility, with no title and no invitation to
#                              ask whether this is a side project.
#   "built this one"         — "this one" implies others exist, so the reader
#                              infers a builder without the copy claiming range.
#   "for {audience}"         — the TOOL is purpose-built for their profession.
#                              A machine made it, but it was made for people
#                              like them.
#
# What is NOT here any more: "after hearing the same thing over and over,
# referrals dried up and nothing replaced them." It was the strongest-reading
# clause in the email and it was not true. It asserts that many people in the
# reader's profession told me this; the real total is 30 emails sent once, two
# replies and one call. Borrowed social proof is exactly the kind of claim this
# system refuses everywhere else — every lead line is a checkable fact off a
# filing — and it cannot hold copy to a standard the pitch itself breaks.
#
# The replacement keeps the three jobs that were honest (credibility, "this
# one" implying others, purpose-built for their profession) and drops the one
# that was invented. House style: all lowercase, no em dashes.
#
# 2026-10-24, the user's rewrite for the finance packs: say what makes the gift
# different (not a bought list; each company comes with its reason) and what
# it does for the reader (a reason to reach out). Deliberately NOT "in real
# time" or "public records": the inventory is refreshed by hand and its audit
# filings are months old, so "real time" is a claim a reader could catch.
#
# Same day, shortened: "these aren't from a list" and "each one comes with a
# reason to reach out" are both obvious once the reader has seen the list, so
# "finds companies like these" carries them.
#
# 2026-10-25: "built ... built" said twice in one sentence, and "companies"
# called a list of charities companies. The noun now follows the leads.
#
# Same day, the user's rewrite: say what the system looks for (signs of need),
# not who it was built for. The pack names the help in the reader's own trade:
# accounting firms read "accounting help", bookkeepers "bookkeeping help", and
# cfo and neutral firms "finance help" ("cfo help" is not a phrase anyone says).
LEFT_FIELD = (
    "i'm an engineer. i built a system that finds {things} showing signs they "
    "need {help} help."
)
_HELP_WORD = {"cfo": "finance", "finance": "finance", "accounting": "accounting",
              "bookkeeping": "bookkeeping"}
# The IT packs (`--legacy-niche`) gift breaches and IT hires, not finance need,
# so they keep the line that names no need.
_LEGACY_LEFT_FIELD = (
    "i'm an engineer. i build these lead systems, and this one is for "
    "{audience}."
)
_FINANCE_PACKS = frozenset({"cfo", "accounting", "bookkeeping", "finance"})


def _org_noun(gift: Gift | None) -> str:
    """"organizations" when every lead is a nonprofit or another non-company
    (a school, a union, a local government, a credit union...: `copy.duty`'s
    `org`), else "companies"."""
    leads = gift.leads if gift is not None else []
    if leads and all(ld.signal_type == NONPROFIT_SIGNAL or ld.industry == "nonprofit"
                     or all_organizations([ld]) for ld in leads):
        return "organizations"
    return "companies"


def left_field_for(pack, gift: Gift | None = None) -> str:
    """The 5b line for a pack: the finance packs name the help in their own
    trade (`_HELP_WORD`); the IT packs keep naming their buyer (`dm_audience`)."""
    if pack.key not in _FINANCE_PACKS:
        return _LEGACY_LEFT_FIELD.format(audience=pack.dm_audience)
    return LEFT_FIELD.format(things=_org_noun(gift), help=_HELP_WORD[pack.key])


@dataclass
class EmailDraft:
    subject: str
    body: str
    flags: list[str] = field(default_factory=list)
    # The trailing part of `body` that is IDENTICAL on every prospect in a run
    # (the left-field line + the CTA). Carried as an exact suffix so the review
    # gate can dim it instead of showing the same two paragraphs on every card,
    # and can re-join head + tail into the original body without guessing where
    # the seam was. Empty on follow-ups, which have no shared tail.
    shared_tail: str = ""

    @property
    def head(self) -> str:
        """`body` minus `shared_tail` — the part that actually varies."""
        if self.shared_tail and self.body.endswith(self.shared_tail):
            return self.body[: -len(self.shared_tail)].rstrip("\n")
        return self.body



# Words that mark a name as a specific ORGANIZATION rather than a brand. A name
# carrying one of these reads unambiguously as a company someone was engaged by,
# which is what "you've worked with X" is claiming.
_ORG_MARKER_RE = re.compile(
    r"\b(?:inc|llc|llp|ltd|corp|corporation|co|company|group|partners|holdings|"
    r"foundation|association|institute|center|centre|society|council|trust|fund|"
    r"alliance|coalition|network|federation|ministries|church|academy|school|"
    r"university|hospital|clinic|services|solutions|systems)\b\.?",
    re.IGNORECASE,
)


def _client_sort_key(name: str) -> tuple[int, int]:
    """Rank a verified client name for use in copy: organizations first, then
    shortest.

    Taking whatever the model returned first put "Humans of New York" — a
    famous brand with millions of followers — in front of a solo fractional CFO
    as a claimed client, while `MAPS` and `Public Justice Foundation` sat unused
    two rows down. A bare brand name is both the likeliest to be something other
    than a client (a partner, an admired project, an "as seen in" logo) and the
    likeliest to read as name-dropping rather than as proof anyone read the page.

    Length breaks the tie because these are printed inline: a 57-character name
    swallows the sentence it is supposed to personalize."""
    return (0 if _ORG_MARKER_RE.search(name) else 1, len(name))


def _client_names_phrase(prospect: Prospect) -> str:
    """"A and B" from the prospect's nameable clients, or "" when there are
    none to stand behind.

    TWO names, not one and not five: one reads as a lucky grep, five reads as a
    scrape. Two is the smallest number that shows someone actually read the
    page. Names keep their own casing (they are proper nouns) inside otherwise
    lowercase prose, exactly as the gift's company names do."""
    names = [n.strip() for n in (prospect.client_names or []) if n and n.strip()]
    if len(names) < 2:
        return ""
    best = [spoken_name(n) for n in sorted(names, key=_client_sort_key)[:2]]
    return f"{best[0]} and {best[1]}"


# The CFO pack's value-prop clause. Named because `_framing` and
# `_revenue_framing` must say the same thing, and they drifted while it was a
# literal repeated seven times.
_CFO_NEED = "showing they need finance help"


# Magnet signal types (the phrases for each are further down).
NONPROFIT_SIGNAL = "nonprofit_grant_no_finance_officer"
FUNDS_SIGNAL = "adv_no_fund_administrator"
ECOMMERCE_SIGNAL = "ecommerce_sku_load_no_finance_staff"
# The lead inventory's record-based signals (2026-10-18). Each is an EVENT on a
# public record -- an award, a license, a contract, a grant, a formation --
# not an absence, and none is a job post or a raise.
DAVIS_BACON_SIGNAL = "construction_federal_award_davis_bacon"
NEW_LICENSE_SIGNAL = "construction_new_licensed_business"
LICENSE_UPGRADE_SIGNAL = "construction_license_upgrade"
COST_CONTRACT_SIGNAL = "federal_cost_reimbursement_contract"
FIRST_GRANT_SIGNAL = "federal_first_time_grant"
NEW_BUSINESS_SIGNAL = "new_business_formed"

RECORD_SIGNALS = frozenset({
    DAVIS_BACON_SIGNAL, NEW_LICENSE_SIGNAL, LICENSE_UPGRADE_SIGNAL,
    COST_CONTRACT_SIGNAL, FIRST_GRANT_SIGNAL, NEW_BUSINESS_SIGNAL,
}) | DUTY_SIGNALS          # + the legal-duty types (2026-10-27, `copy.duty`)

MAGNET_SIGNALS = frozenset({NONPROFIT_SIGNAL, FUNDS_SIGNAL, ECOMMERCE_SIGNAL}) | RECORD_SIGNALS


# Each magnet's value-prop clause, in the words its own filter can support.
#
# The magnets verify an ABSENCE, and the job-post packs' wording claims the
# opposite. "building out their finance function right now" (accounting) and
# "looking for bookkeeping help right now" (bookkeeping) describe a company
# that ADVERTISED a role -- which is precisely what a magnet lead did not do;
# it published nothing, which is why we had to read a filing to find it. Sent
# as-is, an ADV gift opened "3 more building out their finance function right
# now" about firms whose only disclosed fact is that their funds have no
# third-party administrator.
#
# Same rule as `_MAGNET_WHAT` in gift.engine: one clause per magnet, never one
# shared word, because the three do not verify the same thing. Funds says
# nothing about who works there.
_MAGNET_NEED: dict[str, str] = {
    "nonprofit_grant_no_finance_officer": "showing they need finance help",
    "adv_no_fund_administrator": "running funds with no administrator",
    "ecommerce_sku_load_no_finance_staff": "with nobody in finance",
    # The record-based signals: the event each record shows, nothing more.
    DAVIS_BACON_SIGNAL: "on federal jobs with weekly certified payroll",
    NEW_LICENSE_SIGNAL: "with a new contractor license",
    LICENSE_UPGRADE_SIGNAL: "moving up to a bigger contractor license",
    COST_CONTRACT_SIGNAL: "on federal contracts the government can audit",
    FIRST_GRANT_SIGNAL: "with their first federal grant in 3+ years",
    NEW_BUSINESS_SIGNAL: "newly registered with the state",
    # The legal-duty types (`copy.duty`): the record's own predicate.
    **{t: d.need_clause for t, d in DUTIES.items()},
}

# A gift mixing record-based signals (an award, a license, a 990 audit
# finding, a formation) states what each record SHOWS: a need for finance
# help. The pack defaults ("looking for bookkeeping help right now") describe
# a company that advertised a role, which none of these did. Funds and
# ecommerce stay out: their filters verify an absence this does not cover.
_MIXED_RECORD_NEED = "showing they need finance help"
_RECORD_FAMILY = RECORD_SIGNALS | {NONPROFIT_SIGNAL}


def need_for(gift: Gift, *, default: str) -> str:
    """The value-prop clause to use for this gift.

    A gift built entirely from ONE magnet speaks that magnet's language; any
    other gift keeps the pack's own wording. Mixed-magnet gifts fall back too:
    there is no honest single clause covering both an unstaffed nonprofit and a
    fund with no administrator.
    """
    kinds = {lead.signal_type for lead in gift.leads}
    if len(kinds) == 1:
        return _MAGNET_NEED.get(next(iter(kinds)), default)
    if kinds and kinds <= _RECORD_FAMILY:
        return _MIXED_RECORD_NEED
    return default


def _revenue_framing(gift: Gift, prospect: Prospect, niche: str | None, *, need: str) -> str:
    """The opener when the prospect stated a client-revenue range on their site.

    TWO sentences, deliberately. "saw you work with $2m-$10m companies, SO i
    pulled 3 in atlanta" would imply we filtered on revenue — and we cannot.
    Leadgen publishes no revenue field, and a probe of 25 inventory companies
    found grounded estimates unusable, so a revenue-matched gift is not
    something this system can honestly assemble.

    Splitting the sentence keeps each half true on its own: the first states
    what they told us about themselves (verified verbatim), the second states
    exactly what was matched (niche and/or geography). The reader gets the proof
    that someone read their site without being promised a filter that isn't
    there.

    This is the biggest upgrade for GENERALIST prospects, whose opener is
    otherwise "saw you're based in atlanta" — an Apollo merge field that proves
    nothing about whether we looked at them at all.

    `need` is the pack's value-prop clause, threaded through so every pack gets
    this lever in its own words. It used to be hardcoded to the CFO wording,
    which is why only the CFO pack could reach this function at all — and why
    the review gate's `_personalization` ranked bookkeeping and accounting cards
    for a revenue opener their copy never actually wrote."""
    n = gift.gift_size
    rev = revenue_display(prospect.client_revenue)
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    companies = lead_noun(gift, n)   # "nonprofits" when every lead is one

    if niche:
        read = f"saw you work with {rev} {niche_noun(niche)}."
        pulled = f"pulled {n} more {need}:"
    else:
        read = f"saw you work with {rev} companies."
        if gift.geo_level == "city" and city:
            pulled = f"pulled {n} {companies} in {city} {need}:"
        elif gift.geo_level == "state" and (state or city):
            pulled = f"pulled {n} {companies} in {state} {need}:"
        else:
            pulled = f"pulled {n} {companies} {need}:"
    return f"{read} {pulled}"


def _framing(gift: Gift, prospect: Prospect) -> str:
    n = gift.gift_size
    niche = niche_claim(gift, prospect)
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    # Revenue is the second personalization lever (23% of prospects state one).
    # It stacks with niche and geography rather than replacing them, and it is
    # skipped for a client-list opener, which already names two of their actual
    # clients and needs no further proof that we read the page.
    if prospect.client_revenue and prospect.niche_source != "client_list":
        return _revenue_framing(gift, prospect, niche, need=_CFO_NEED)
    # Framing ALWAYS uses the clean mapped niche word (niche_claim -> niche_display),
    # NEVER the raw scraped phrase — the verbatim phrase is often a nav blob
    # ("WHO WE SERVE...", "designed for:") and can leak a dollar figure. The
    # exact phrase stays in evidence / the review card, not the sent copy.
    # The VERB stays soft — "work with", never "focus on" — so we never overclaim
    # a specialty we might be wrong about. A client list reads as a sole focus.
    companies = lead_noun(gift, n)   # "nonprofits" when every lead is one
    if niche:
        if prospect.niche_source == "client_list":
            # Naming the clients is what makes a 2-client threshold honest. The
            # unnamed version ("a bunch of nonprofit companies") is an inference
            # about their BUSINESS from two data points; naming them makes it a
            # citation of two facts verbatim on their own page. `client_names`
            # is already filtered to client-indicating pages upstream, and is
            # empty when we can't stand behind it — in which case we fall back
            # to the soft, unnamed phrasing.
            named = _client_names_phrase(prospect)
            if named:
                return (
                    f"noticed you've worked with {niche_noun(niche)} like {named}, "
                    f"so i pulled {n} more {_CFO_NEED}:"
                )
            return (
                f"noticed you've worked with {niche_noun(niche)}, so i "
                f"pulled {n} more {_CFO_NEED}:"
            )
        if prospect.niche_exclusivity == "one_of_several":
            # one of SEVERAL stated industries — name ONLY the one we're gifting.
            return (
                f"noticed you work with {niche_noun(niche)}, so i pulled {n} more "
                f"{_CFO_NEED}:"
            )
        # sole — a single stated focus; still soft language ("work with").
        return (
            # "you work with nonprofits, so i pulled 3 nonprofits" repeats the
            # noun two clauses apart. "more" says the same thing and carries the
            # claim that they already work with these — which is the point.
            f"saw on your site you work with {niche_noun(niche)}, so i pulled "
            f"{n} more {_CFO_NEED}:"
        )
    # geo (all_niche FALSE): open with where they're based ONLY when the leads
    # are actually in their city or state. A geo-none gift's leads are
    # scattered, so it makes no location claim — "saw you're based in [city],
    # so i pulled..." would falsely imply the leads relate to that city.
    based = city or state
    if gift.geo_level == "city" and city:
        return (
            f"saw you're based in {city}, so i pulled {n} {companies} in {city} "
            f"{_CFO_NEED}:"
        )
    if gift.geo_level == "state" and based:
        return (
            f"saw you're based in {based}, so i pulled {n} {state} {companies} "
            f"{_CFO_NEED}:"
        )
    return f"i pulled {n} {companies} {_CFO_NEED}:"


def framing_line(gift: Gift, prospect: Prospect, *, need: str) -> str:
    """Vertical-aware opener with a geo fallback — the shared framing body for the
    non-CFO packs (accounting, msp, mssp, cloud). Mirrors the CFO `_framing`
    structure exactly: it claims a customer vertical ONLY when the gift is
    all-niche (`niche_claim`, which is gated on `prospect.classification=="niched"`
    upstream), otherwise opens on geography, otherwise makes no location claim.

    `need` is the pack's value-prop clause, appended after the companies noun —
    e.g. "that just posted an it support role" or "showing they need bookkeeping
    help right now". Verb stays soft ("work with"), never "focus on"."""
    n = gift.gift_size
    niche = niche_claim(gift, prospect)
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    companies = lead_noun(gift, n)   # "nonprofits" when every lead is one
    # Revenue is the second personalization lever and it is not CFO-specific:
    # 23% of prospects state a client-revenue range, and the prospects it helps
    # most are the GENERALISTS in every pack, whose opener is otherwise an Apollo
    # merge field. Same two gates as `_framing`: skipped for a client-list opener,
    # which already names two real clients.
    if prospect.client_revenue and prospect.niche_source != "client_list":
        return _revenue_framing(gift, prospect, niche, need=need)
    if niche:
        if prospect.niche_source == "client_list":
            return (
                f"noticed you've worked with a bunch of {niche_noun(niche)}, so i "
                f"pulled {n} more {need}:"
            )
        if prospect.niche_exclusivity == "one_of_several":
            return f"noticed you work with {niche_noun(niche)}, so i pulled {n} more {need}:"
        return (f"saw on your site you work with {niche_noun(niche)}, so i pulled "
                f"{n} more {need}:")
    based = city or state
    if gift.geo_level == "city" and city:
        return f"saw you're based in {city}, so i pulled {n} {companies} in {city} {need}:"
    if gift.geo_level == "state" and based:
        return f"saw you're based in {based}, so i pulled {n} {state} {companies} {need}:"
    return f"i pulled {n} {companies} {need}:"


# --- The record opener (2026-10-24) ------------------------------------------
#
# Every lead the finance packs gift is now an inventory RECORD (an audit, an
# award, a license, a grant, a filing). When all of an email's leads share one
# kind of record, the opener states that shared fact ONCE, with why it matters
# in the same sentence, and the lines carry only what differs. Before,
# "auditors flagged ..." was said three times and the opener promised a vague
# "need".
#
#   saw you work with $3m+ nonprofits. these 3 in atlanta had weak financial
#   controls flagged in their federal audits, so each now has to file a plan
#   to fix it:
#
#   1. Georgia Court Appointed Special Advocates (two years in a row)
#   2. Cathedral Towers
#   3. Georgia Works (two years in a row)
#
# Three rules keep it honest:
#   - The "why it matters" clause is a rule that follows from the record itself
#     (a federal audit finding needs a corrective action plan, 2 CFR 200.511;
#     Davis-Bacon needs weekly certified payroll, FAR 22.406-6; a cost-type
#     contract needs an adequate accounting system, FAR 16.301-3; a federal
#     award carries the Uniform Guidance's tracking and reporting rules). A
#     license or a new registration implies no such rule, so it gets none:
#     "books not set up yet" was a guess and was removed on 2026-10-18.
#   - A place is named only when EVERY lead is there (same city in the same
#     state, else the same state). The old opener said "pulled 3 more", whose
#     "more" read as a previous email.
#   - A gift that mixes kinds has no shared fact, so each line keeps its full
#     templated reason, exactly as before, and there is no "why".
#
# Anything outside the record family (the IT packs' breaches and job posts)
# returns None and keeps the old `pack.framing` + `_lead_line` path.

# kind -> (plural clause, singular clause) for the kinds with NO why. The
# clause follows the noun: "here are 3 in tampa {clause}:".
_RECORD_CLAUSE: dict[str, tuple[str, str]] = {
    NEW_LICENSE_SIGNAL: ("with a new contractor license",
                         "with a new contractor license"),
    LICENSE_UPGRADE_SIGNAL: ("that moved up to a bigger contractor license",
                             "that moved up to a bigger contractor license"),
    NEW_BUSINESS_SIGNAL: ("that just registered as new companies",
                          "that just registered as a new company"),
    "mixed": ("that need finance help", "that needs finance help"),
}

# kind -> ((plural predicate, singular predicate), (plural why, singular why))
# for the kinds where a rule follows from the record. These open as ONE
# sentence, what happened and why it matters before the list (2026-10-24):
#   "these 3 in atlanta had weak financial controls flagged in their federal
#    audits, so each now has to file a plan to fix it:"
# Kinds absent here keep "here are 3 ... {clause}:" and get no why.
# 2026-10-25: was "so each now has to file a plan to fix it". The corrective
# action plan is filed WITH the audit (2 CFR 200.511(c)), so for an audit on
# file it already exists and "has to file" is false. What stays true until the
# finding is resolved: the next audit's summary schedule of prior findings has
# to report it fixed (200.511(b)). Present tense, any audit age, and a deadline.
_AUDIT_WHY = ("and each has to show it's fixed in its next audit",
              "and it has to show it's fixed in its next audit")
_RECORD_WHY: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "audit_controls": (("had weak financial controls flagged in their federal audits",
                        "had weak financial controls flagged in its federal audit"),
                       _AUDIT_WHY),
    "audit_grants": (("had their grant handling flagged in their federal audits",
                      "had its grant handling flagged in its federal audit"),
                     _AUDIT_WHY),
    "audit_mixed": (("had problems flagged in their federal audits",
                     "had problems flagged in its federal audit"),
                    _AUDIT_WHY),
    DAVIS_BACON_SIGNAL: (("won federal construction jobs",
                          "won a federal construction job"),
                         ("so each now owes weekly certified payroll for every worker",
                          "so it now owes weekly certified payroll for every worker")),
    "cost_every": (("won federal contracts where every cost can be audited",
                    "won a federal contract where every cost can be audited"),
                   ("so each needs books that can pass a government audit",
                    "so it needs books that can pass a government audit")),
    COST_CONTRACT_SIGNAL: (("won federal contracts the government can audit",
                            "won a federal contract the government can audit"),
                           ("so each needs books that can pass a government audit",
                            "so it needs books that can pass a government audit")),
    FIRST_GRANT_SIGNAL: (("got their first federal grant in 3+ years",
                          "got its first federal grant in 3+ years"),
                         ("so each now has strict tracking and reporting rules to follow",
                          "so it now has strict tracking and reporting rules to follow")),
}


def _audit_facts(lead: Lead) -> tuple[str, bool] | None:
    """("controls" | "grants", repeat) for a nonprofit whose audit has a
    finding, read off the same `nonprofit_phrase` the full line uses so the two
    can never disagree; None for a late or missing audit (no finding)."""
    phrase = nonprofit_phrase(lead)
    repeat = phrase.endswith("two years running")
    if phrase.startswith("auditors flagged their"):
        return "controls", repeat
    if phrase.startswith("auditors flagged how they handle grants"):
        return "grants", repeat
    return None


def _record_kind(gift: Gift) -> str | None:
    """The fact every lead shares, "mixed" when they share none, or None when a
    lead is outside the record family (legacy path)."""
    leads = gift.leads
    if not leads or any(ld.signal_type not in _RECORD_FAMILY for ld in leads):
        return None
    kinds = {ld.signal_type for ld in leads}
    if len(kinds) > 1:
        return "mixed"
    kind = next(iter(kinds))
    if kind == NONPROFIT_SIGNAL:
        facts = [_audit_facts(ld) for ld in leads]
        if any(f is None for f in facts):
            return "mixed"
        found = {f[0] for f in facts}
        return {"controls": "audit_controls", "grants": "audit_grants"}.get(
            next(iter(found)), "audit_mixed") if len(found) == 1 else "audit_mixed"
    if kind == COST_CONTRACT_SIGNAL and all(
            _payload(ld).get("pricing_kind") == "cost-reimbursement" for ld in leads):
        return "cost_every"
    return kind


def _record_detail(lead: Lead, kind: str) -> str:
    """Only what differs between leads that share `kind`; "" for nothing."""
    if kind in DUTIES:
        return DUTIES[kind].detail_for(lead)
    p = _payload(lead)
    if kind.startswith("audit_"):
        what, repeat = _audit_facts(lead) or ("", False)
        bits = []
        if kind == "audit_mixed":
            bits.append("financial controls" if what == "controls" else "grant handling")
        if repeat:
            bits.append("two years in a row")
        return ", ".join(bits)
    if kind == DAVIS_BACON_SIGNAL:
        if p.get("first_contract_on_record"):
            return "first on record"
        n = p.get("awards_in_window")
        return "more than one" if isinstance(n, int) and n > 1 else ""
    if kind == COST_CONTRACT_SIGNAL:
        return "hourly" if p.get("pricing_kind") in ("time-and-materials", "labor-hour") else ""
    if kind == NEW_LICENSE_SIGNAL:
        bits = ["new company"] if p.get("formed_class") == "new_company" else []
        where = _elsewhere(lead, _licensing_state(lead))
        if where:
            bits.append("licensed" + where)
        return ", ".join(bits)
    if kind == LICENSE_UPGRADE_SIGNAL:
        cls = _LICENSE_CLASS.get(str(p.get("license_class") or "").upper())
        issuer = _elsewhere(lead, _licensing_state(lead) or "FL").removeprefix(" in ")
        return " ".join(w for w in (issuer, cls, "contractor" if cls else "") if w)
    if kind == NEW_BUSINESS_SIGNAL:
        where = _elsewhere(lead, p.get("state"))
        return "registered" + where if where else ""
    return ""


def _shared_place(gift: Gift) -> tuple[str, str]:
    """("city" | "state" | "", display) for where EVERY lead is. A city counts
    only within one state: arlington WA is not arlington TX."""
    leads = gift.leads
    cities = {(city_display(ld.city), state_display(ld.state)) for ld in leads}
    if len(cities) == 1:
        city, state = next(iter(cities))
        if city and state:
            return "city", city
    states = {state_display(ld.state) for ld in leads}
    if len(states) == 1:
        state = next(iter(states))
        if state:
            return "state", state
    return "", ""


def _record_read(gift: Gift, prospect: Prospect, place: tuple[str, str]) -> str:
    """The first sentence: what we saw about THEM. Same evidence and the same
    soft verbs as `_framing`; empty when we can honestly say nothing."""
    niche = niche_claim(gift, prospect)
    if prospect.client_revenue and prospect.niche_source != "client_list":
        rev = revenue_display(prospect.client_revenue)
        return f"saw you work with {rev} {niche_noun(niche) if niche else 'companies'}."
    if niche:
        if prospect.niche_source == "client_list":
            named = _client_names_phrase(prospect)
            if named:
                return f"noticed you've worked with {niche_noun(niche)} like {named}."
            return f"noticed you've worked with {niche_noun(niche)}."
        if prospect.niche_exclusivity == "one_of_several":
            return f"noticed you work with {niche_noun(niche)}."
        return f"saw on your site you work with {niche_noun(niche)}."
    # Geography is claimed about them only when the leads really are there.
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    level, where = place
    if level == "city" and city == where and state_display(prospect.state):
        return f"saw you're based in {city}."
    if level == "state" and state == where:
        return f"saw you're based in {city or state}." if city else f"saw you're based in {state}."
    return ""


def record_opener(gift: Gift, prospect: Prospect) -> tuple[str, list[str]] | None:
    """(framing, lead lines without numbers) for a record gift, or None to keep
    the legacy path."""
    kind = _record_kind(gift)
    if kind is None:
        return None
    n = gift.gift_size
    place = _shared_place(gift)
    level, where = place
    niche = niche_claim(gift, prospect)
    one = 0 if n != 1 else 1
    noun = "" if niche else lead_noun(gift, n)
    at = f"in {where}" if where else ""
    duty = DUTIES.get(kind)
    if duty is not None:
        # The legal-duty types (2026-10-27): the same "these 3 ... predicate[,
        # why]:" sentence, the why only where `copy.duty` gives one.
        count = f"these {n}" if n != 1 else ("this" if noun else "this one")
        why = duty.why_for(gift.leads)
        ask = " ".join(w for w in (count, noun, at, duty.predicate(gift.leads)) if w) \
            + (f", {why}:" if why else ":")
    elif kind in _RECORD_WHY:
        predicates, whys = _RECORD_WHY[kind]
        count = f"these {n}" if n != 1 else ("this" if noun else "this one")
        ask = " ".join(w for w in (count, noun, at, predicates[one]) if w) \
            + f", {whys[one]}:"
    else:
        clause = _RECORD_CLAUSE[kind][one]
        count = "here are " + str(n) if n != 1 else "here's one"
        if noun and n == 1:
            count = "here's a" + ("n" if noun[0] in "aeiou" else "")
        ask = " ".join(w for w in (count, noun, at, clause) if w) + ":"
    read = _record_read(gift, prospect, place)
    framing = f"{read} {ask}" if read else ask

    lines = []
    for lead in gift.leads:
        said = spoken_name(lead.company)
        # The city is already in the opener when every lead shares it, and so
        # is the state when a lead has no city of its own (a film production:
        # "1. Glue The Film, california" said the state three times).
        loc = "" if level == "city" or (level == "state" and not city_display(lead.city)) \
            else (city_display(lead.city) or state_display(lead.state))
        name = f"{said}, {loc}" if loc else said
        if kind == "mixed":
            lines.append(f"{name}: {magnet_phrase(lead)}")
        else:
            detail = _record_detail(lead, kind)
            lines.append(f"{name} ({detail})" if detail else name)
    return framing, lines


# The ask. One goal per email: book 15 minutes.
#
# The previous CTA ("want me to keep an eye out for atlanta ones?") optimized
# for the WRONG yes — it recruited subscribers to a free lead feed, which is
# the one business this tool is not trying to be in, and it never converted to
# a conversation. Every part of this one is deliberate:
#
#   "still tuning it"       — true, and it turns a sales ask into a research
#                             ask. People delete the first and answer the
#                             second. It also covers a weak lead honestly.
#   "would 15 min work"     — a bounded, specific, easily-declined request.
#   "what would make it     — the call's stated purpose is THEIR expertise, not
#    useful for you"          a pitch, and it opens onto everything else they
#                             need once you are actually talking.
#   "either way"            — they get the thing whether or not they take the
#                             call. Removes the transaction; this is the most
#                             persuasive clause in the email precisely because
#                             it asks for nothing.
#
# Niche/geo-agnostic on purpose: the opener and the leads already carried the
# personalization, and repeating it here made the close about the feed again.
# A BINARY ask, not a calendar ask. "would 15 min work" asks the reader to
# check a calendar and commit a slot before they know whether the thing is any
# good; "worth a look?" asks for a yes or a no, which is a decision they can
# make from the email they are already reading. The offer to run it either way
# stays, because it is the part that costs them nothing.
#
# 2026-10-24: "still tuning it." cut in the user's shortening pass (the body
# went from ~80 words to ~55). The trade-off was put to them: it made the ask
# read as research rather than sales.
_CTA_LINE = "worth a look? happy to set it up for you either way :)"


def _cta(gift: Gift, prospect: Prospect) -> str:
    return _CTA_LINE


def _funding_phrase(lead: Lead) -> str:
    """Canonical, code-templated raise description (#10): consistent across the
    batch, never a dollar amount. A Form C filing is crowdfunding (Reg CF); a
    Form D is a filed private raise. Shared by every pack whose `raise_signals`
    cover the SEC funding types (cfo, accounting, cloud)."""
    if lead.signal_type == "funding_form_c":
        return "just raised via crowdfunding"
    raw = " ".join((s.plain_words_description or "") for s in lead.signals).lower()
    if any(k in raw for k in ("reg cf", "regulation crowdfunding", "form c", "crowdfund")):
        return "just raised via crowdfunding"
    return "just filed to raise"


def _has_funding_signal(lead: Lead, raise_signals) -> bool:
    """True if the lead carries a funding signal ANYWHERE (not just as its
    primary signal_type). A hire-primary lead that also raised is a "double" —
    the highest-intent gift."""
    return any(s.type in raise_signals for s in lead.signals)


def is_job_posting(lead: Lead) -> bool:
    """A hiring signal — the company POSTED a role, so the seat is OPEN (that's
    the buying signal). Every leadgen job signal type is `job_*`."""
    return (lead.signal_type or "").startswith("job_")


# Trailing metadata job boards weld onto a title. Each was chosen against real
# inventory titles, and each is stripped ONLY at the end of the string, because
# the same words mid-title can be the role itself.
#
# Parentheticals are almost always board noise — "(Phoenix)", "(Remote)",
# "(Full-Time)", "(In Office)", "(part-time, no agencies, pacific time zone
# only)". Stripping every trailing one is safe; nothing in copy needs them.
_TRAILING_PARENS_RE = re.compile(r"(?:\s*\([^()]*\))+\s*$")

# A dash segment is a different matter: "- Manufacturing", "- Private Equity",
# "- Billing & Operations" and "- FP&A" all describe the ROLE and must survive.
# Only two shapes get cut — a place, and a work arrangement — because those are
# the ones that duplicate or contradict the city the line already prints
# ("F3EA Inc, savannah: is looking for a financial controller - savannah, ga").
# Case matters differently per branch, so IGNORECASE is scoped, not global: the
# "City, ST" branch needs the two letters to be UPPERCASE (that is what tells a
# state from an ordinary word, so "Controller - Finance, hr" survives), while
# the arrangement branch has to catch "Hybrid" and "Remote" as written.
_TRAILING_LOCATION_RE = re.compile(
    r"\s*[-–—]\s*(?:"
    r"[A-Za-z .'\-]+,\s*[A-Z]{2}"                        # "Savannah, GA"
    r"|(?i:(?:\d+%\s*)?(?:remote|onsite|on-site|hybrid|in[\s-]office)"
    r"(?:[\s/](?:remote|onsite|on-site|hybrid|role))*)"  # "75% Remote", "Onsite/Hybrid role"
    r")\s*$"
)


def _clean_role(raw: str) -> str:
    """The posting title with board metadata removed, casing intact.

    Runs BEFORE lowercasing on purpose: the "City, ST" test needs the two
    capital letters to tell a state from an ordinary word."""
    role = raw.split("|", 1)[0].strip()
    for _ in range(3):                     # titles stack them: "... (In Office) (Phoenix)"
        stripped = _TRAILING_LOCATION_RE.sub("", _TRAILING_PARENS_RE.sub("", role)).strip()
        if stripped == role:
            break
        role = stripped
    return role.strip(" -–—,")


# Titles a person says as initials. A job board writes "Chief Financial Officer";
# nobody says that out loud to another finance person, they say "CFO" — and the
# expanded form in an otherwise casual lowercase line is a tell that the sentence
# was assembled rather than written.
#
# Longest-first, because "chief information security officer" contains "chief
# information officer" and would otherwise be half-replaced into nonsense.
# Deliberately excludes "chief accounting officer": CFO and CISO are universally
# spoken as initials, CAO is not.
_ROLE_ABBREVIATIONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{p}\b", re.IGNORECASE), r)
    for p, r in (
        ("chief information security officer", "ciso"),
        ("chief financial officer", "cfo"),
        ("chief technology officer", "cto"),
        ("chief information officer", "cio"),
        ("chief operating officer", "coo"),
        ("chief executive officer", "ceo"),
        ("chief revenue officer", "cro"),
        ("financial planning and analysis", "fp&a"),
        ("financial planning & analysis", "fp&a"),
        ("vice president", "vp"),
    )
)

# A title that spelled a term out AND parenthesised its initials reads as
# "head of fp&a (fp&a)" once abbreviated. Drop the parenthetical when it merely
# repeats something already in the line.
_TRAILING_ABBREV_RE = re.compile(r"\s*\(([^()]{1,12})\)\s*$")


def _spoken_role(role: str) -> str:
    """The role as a person would say it: initials where initials are what gets
    said, and no parenthetical that just repeats them."""
    for pattern, replacement in _ROLE_ABBREVIATIONS:
        role = pattern.sub(replacement, role)
    m = _TRAILING_ABBREV_RE.search(role)
    if m and m.group(1).strip().lower() in role[: m.start()].lower():
        role = role[: m.start()].strip()
    return role


def job_role(lead: Lead) -> str:
    """The posting's role WITH its article — `a head of finance`, `an interim
    cfo` — or `""` when the title yields nothing usable.

    Factored out of `job_phrase` because both channels need the same words in
    different frames: the email says "is looking for {role}", the LinkedIn DM
    says "hiring {role}". Deriving the DM's wording from the email's rendered
    sentence would mean string-surgery on copy, so the shared unit is the role
    itself."""
    headline = lead.headline_signal
    raw = (headline.plain_words_description if headline else "") or ""
    role = _clean_role(raw).lower()
    role, _ = strip_dollar_amounts(role)          # a salary in the title never reaches copy
    role = role.strip()
    if not role:
        return ""
    # Put the part-time word back when the posting said it in the body but not
    # the title. Without this the subject promises "a fractional cfo" and the
    # line under it reads "is looking for a chief financial officer", so the
    # reader looks for the fractional role and cannot find it. The word is the
    # posting's OWN (see clients.inventory._fractional_qualifier) — never a
    # generic default — and is omitted entirely when we cannot name it.
    qualifier = (lead.role_qualifier or "").strip().lower()
    if qualifier and qualifier not in role:
        role = f"{qualifier} {role}"
    return fix_articles(f"a {_spoken_role(role)}")


def job_phrase(lead: Lead) -> str:
    """Deterministic hiring line for a job-posting lead: `is looking for a
    {role}`. `{role}` is the posting's title from the lead's evidence, stripped
    of the `| location | salary` and trailing board metadata that reads as noise
    in copy (it all stays in the review evidence). NEVER says "hired" — the role
    is open, which is the whole point. Templated (not LLM) for the same reason
    funding is: honesty lives in code."""
    role = job_role(lead)
    return f"is looking for {role}" if role else "is hiring"


def is_breach(lead: Lead) -> bool:
    return (lead.signal_type or "") == "breach_disclosed"


def breach_phrase(lead: Lead) -> str:
    """Deterministic line for a breach lead: `disclosed a security incident`.

    Templated for the same reason hiring and funding are: the disclosure is a
    matter of public record, and code cannot embellish it. Deliberately SOFT
    and specific-free — the MSSP pack's own operator flag says to keep it that
    way, and the underlying record ("... reported a data breach (07/24/2026,
    California AG)") carries details this line must not repeat."""
    return "disclosed a security incident"


# --- Vertical magnet phrases ------------------------------------------------
#
# One templated line per lead magnet, for the same reason hiring, funding and
# breach are templated: the underlying record is a public filing, and code must
# not embellish it.
#
# These exist because the fallback below (`_grounded_line`) is the wrong shape
# for a magnet lead. It returns the lead's full `evidence_text`, which for a
# nonprofit runs ~60 words and is then LOWERCASED and stripped of every dollar
# figure by the safety net downstream -- leaving a long sentence with its
# substance removed, and raising a review flag on every single lead. The full
# evidence is exactly right for the review gate, where the operator checks the
# claim; it is the wrong thing to paste into an email that must total under 80
# words.
#
# So each phrase below states the ONE fact that makes the company a buyer, in
# the plainest words available, with no figure the recipient cannot verify in
# one click via the lead's source_url.



def is_magnet_lead(lead: Lead) -> bool:
    return (lead.signal_type or "") in MAGNET_SIGNALS


def _payload(lead: Lead) -> dict:
    """The primary signal's payload, or {}. Kept defensive: a magnet may ship a
    lead without one, and a missing figure must degrade the sentence rather
    than raise mid-run."""
    for sig in lead.signals:
        data = getattr(sig, "payload", None)
        if isinstance(data, dict) and data:
            return data
    return {}


# Every lead line is capped at roughly EIGHT WORDS.
#
# Three leads sit in an email that should total under 80 words, so a 12-word
# line spends half the budget on the middle of the message and pushes the ask
# past where anyone is still reading. The long, fully-qualified version of each
# claim already exists and is exactly right for the review card, where the
# operator is checking rather than skimming.
#
# The short form keeps the NOUN that makes it checkable ("auditors", "990",
# "administrator") and drops the qualifiers around it. "had a material weakness
# in financial controls flagged in two straight federal audits" becomes
# "auditors flagged their controls, two years running" -- same fact, same
# source, half the words, and it sounds like a person rather than a filing.


def nonprofit_phrase(lead: Lead) -> str:
    """`auditors flagged their controls, two years running`.

    Strongest true reason first. A material weakness is an independent CPA's
    written conclusion filed federally -- the closest thing in any magnet to
    the buyer's own problem stated by someone else -- so it is what the line
    says whenever it is there. No dollar amounts: the figure is one click away
    on the linked filing, and a number that has since moved is worse than
    none."""
    p = _payload(lead)
    if p.get("fac_repeat_material_weakness"):
        return "auditors flagged their controls, two years running"
    if p.get("fac_material_weakness"):
        return "auditors flagged their financial controls"
    # A significant deficiency is the grade below a weakness, and still a CPA
    # flagging the controls -- the same short form is true of both.
    if p.get("fac_significant_deficiency"):
        if p.get("fac_prior_control_finding"):
            return "auditors flagged their controls, two years running"
        return "auditors flagged their financial controls"
    # A finding on a federal PROGRAM: how they handle the grant money itself
    # (a control finding on the program, or material noncompliance with its
    # terms). "two years running" only when the auditor marked it a repeat.
    if p.get("fac_program_control_finding") or p.get("fac_material_noncompliance"):
        if p.get("fac_program_repeat"):
            return "auditors flagged how they handle grants, two years running"
        return "auditors flagged how they handle grants"
    # The dated problems. "Not on file" and "months late" are both read
    # straight off clearinghouse dates; neither says they MISSED anything,
    # since an agency can grant an extension. No fiscal-year label: lead lines
    # are lowercased prose, and "fy2024" reads as a typo.
    if p.get("fac_overdue"):
        return "their next federal audit isn't on file"
    days = p.get("fac_days_late")
    if p.get("fac_late") and isinstance(days, int) and days >= 60:
        return f"filed their federal audit {days // 30} months late"
    # An organization can now qualify on its audit alone while LISTING a
    # finance officer, so the absence is only claimed when the 990 says so.
    # Inventories from before the field existed passed the Part VII filter
    # by construction, hence the True default.
    if not p.get("no_finance_officer_listed", True):
        if p.get("fac_audit_year") or p.get("federal_audit_required"):
            return "files a federal audit every year"
        return "grant funded, files a federal audit"
    if p.get("fac_audit_year") or p.get("federal_audit_required"):
        return "files a federal audit, no finance officer"
    if p.get("audit_flag") == "near_threshold":
        return "nearing a federal audit, no finance officer"
    if p.get("financial_statements_audited") is False:
        return "no audit, no finance officer on their 990"
    share = p.get("government_grant_share")
    if isinstance(share, (int, float)) and share >= 0.5:
        return "mostly grant funded, no finance officer"
    return "grant funded, no finance officer on their 990"


def funds_phrase(lead: Lead) -> str:
    """`runs several funds with no outside administrator`.

    The count is the whole signal, so it is stated -- but as a count of FUNDS,
    never a dollar figure. `unadmin_funds` is deliberately a floor: it counts
    the funds whose Schedule D says no administrator, so it can only ever be
    too low, never wrong."""
    p = _payload(lead)
    n = p.get("unadmin_funds")
    # Custody is the only DATED obligation this magnet has: an adviser holding
    # client assets owes a surprise annual exam by an independent accountant.
    # It leads the line when present, because it is the stronger fact.
    if p.get("has_custody"):
        if isinstance(n, int) and n > 1:
            return f"{n} funds, no administrator, holds client assets"
        return "holds client assets, no fund administrator"
    if isinstance(n, int) and n > 1:
        return f"{n} funds, no outside administrator"
    if n == 1:
        return "one fund, no outside administrator"
    return "private funds, no outside administrator"


def ecommerce_phrase(lead: Lead) -> str:
    """`sells across shopify and amazon with nobody in finance`.

    SKU counts are stated as a rounded scale rather than an exact number: the
    catalog is crawled live, so the exact figure moves between the crawl and
    the send, and a number that no longer matches when the recipient checks is
    worse than no number."""
    p = _payload(lead)
    channels = [c.strip().lower() for c in
                str(p.get("marketplaces") or "").split(",") if c.strip()]
    skus = p.get("skus")
    if isinstance(skus, int) and skus >= 1000:
        scale = "thousands of skus"
    elif isinstance(skus, int) and skus >= 250:
        scale = "hundreds of skus"
    else:
        scale = "a big catalog"
    # Name ONE marketplace rather than listing every channel: "shopify and
    # amazon and etsy and faire" spends four words on one idea.
    where = f"shopify + {sorted(channels)[0]}" if channels else "shopify"
    return f"{scale}, {where}, nobody in finance"


# --- The inventory's record-based signals ----------------------------------
#
# Each reads ONLY fields the source put in the lead's payload, and says no
# more than that record does. None carries a date or a figure: the record is
# one click away on the lead's source_url.


def davis_bacon_phrase(lead: Lead) -> str:
    """`won a federal job, weekly certified payroll`.

    The award carries Davis-Bacon wage rates, so the contractor owes certified
    payroll every week (FAR 22.406-6). "on record" because the source checked
    USAspending back to FY2008, not a contractor's whole history."""
    p = _payload(lead)
    jobs = "jobs" if isinstance(p.get("awards_in_window"), int) \
        and p["awards_in_window"] > 1 else "job"
    if p.get("first_contract_on_record"):
        return f"first federal {jobs} on record, weekly certified payroll"
    return f"won a federal {jobs}, weekly certified payroll" if jobs == "job" \
        else "won federal jobs, weekly certified payroll"


def _licensing_state(lead: Lead) -> str | None:
    """The state that issued the license (`gift.engine.licensing_state`)."""
    return licensing_state(lead)


def _elsewhere(lead: Lead, issuer: str | None) -> str:
    """` in washington` when the issuing state differs from the state the line
    prints for the lead (a Portland, OR firm licensed in Washington), else
    "". Without it "Acme, portland: newly licensed contractor" reads as an
    Oregon license, which the record does not show."""
    if not issuer:
        return ""
    if state_display(issuer) == state_display(lead.state):
        return ""
    return f" in {state_display(issuer)}"


def new_license_phrase(lead: Lead) -> str:
    """`new contracting company, just licensed` -- only when Florida's
    corporation records show the company itself is new (`formed_class`
    new_company); otherwise all the record shows is the license. Names the
    licensing state when it is not the lead's own."""
    where = _elsewhere(lead, _licensing_state(lead))
    if _payload(lead).get("formed_class") == "new_company":
        return f"new contracting company, just licensed{where}"
    return f"newly licensed{where}" if where else "newly licensed contractor"


_LICENSE_CLASS = {"CGC": "general", "CBC": "building", "CRC": "residential"}


def license_upgrade_phrase(lead: Lead) -> str:
    """`moved up to a general contractor license`: Florida issued a higher
    class (`license_class`) to a contractor who held a lower one."""
    kind = _LICENSE_CLASS.get(str(_payload(lead).get("license_class") or "").upper())
    # "a florida general contractor license": the issuing state, when it is
    # not the lead's own, inside the noun keeps the line at 8 words.
    issuer = _elsewhere(lead, _licensing_state(lead) or "FL").removeprefix(" in ")
    lic = " ".join(w for w in (issuer, kind or "bigger") if w)
    return f"moved up to a {lic} contractor license"


def cost_contract_phrase(lead: Lead) -> str:
    """By pricing kind. Cost-reimbursement: the government reimburses actual
    costs and CAN audit every one. Time-and-materials and labor-hour: paid by
    the hour, and the hours can be audited. A right, never an event
    ("can be audited", not "get audited")."""
    kind = _payload(lead).get("pricing_kind")
    if kind in ("time-and-materials", "labor-hour"):
        return "hourly federal contract, hours can be audited"
    if kind == "cost-reimbursement":
        return "federal contract where every cost is auditable"
    return "federal contract the government can audit"


def first_grant_phrase(lead: Lead) -> str:
    """Worded exactly as the source checked it: no grant on record for this
    recipient in the 3 years before. Never "first ever"."""
    return "first federal grant in 3+ years"


def new_business_phrase(lead: Lead) -> str:
    """A new LLC or corporation on a state registry (Colorado, Connecticut):
    exactly what the filing shows. Names the registry's state when the
    principal office printed for the lead is elsewhere."""
    return f"just registered as a new company{_elsewhere(lead, _payload(lead).get('state'))}"


_MAGNET_PHRASES = {
    NONPROFIT_SIGNAL: nonprofit_phrase,
    FUNDS_SIGNAL: funds_phrase,
    ECOMMERCE_SIGNAL: ecommerce_phrase,
    DAVIS_BACON_SIGNAL: davis_bacon_phrase,
    NEW_LICENSE_SIGNAL: new_license_phrase,
    LICENSE_UPGRADE_SIGNAL: license_upgrade_phrase,
    COST_CONTRACT_SIGNAL: cost_contract_phrase,
    FIRST_GRANT_SIGNAL: first_grant_phrase,
    NEW_BUSINESS_SIGNAL: new_business_phrase,
    **{t: d.phrase for t, d in DUTIES.items()},
}


def magnet_phrase(lead: Lead) -> str:
    """The templated line for a magnet lead."""
    return _MAGNET_PHRASES[lead.signal_type](lead)


def _grounded_line(lead: Lead) -> str:
    """Fallback for a signal type with no template of its own: the lead's own
    verbatim evidence, never a model's paraphrase. Reached only if a new signal
    type is added without a phrase — an honest degradation, not a normal path."""
    headline = lead.headline_signal
    return (headline.plain_words_description if headline else "") or ""


def _lead_line(
    lead: Lead, today: date, geo_level: str, *, pack,
    with_date: bool = True,
) -> tuple[str, list[str]]:
    flags: list[str] = []

    if pack.funding_phrase is not None and is_raise(lead, pack.raise_signals):
        text = pack.funding_phrase(lead)                 # #10: ALL raises templated
    elif is_breach(lead):
        text = breach_phrase(lead)
    else:
        if is_job_posting(lead):
            # Templated hiring line — never the raw "title | location | salary"
            # evidence (goofy in copy).
            text = job_phrase(lead)
        elif is_magnet_lead(lead):
            # Templated vertical line — never the raw filing evidence, which is
            # ~60 words and would arrive lowercased with its figures stripped.
            text = magnet_phrase(lead)
        else:
            text = _grounded_line(lead).strip().lower()
            text, stripped = strip_dollar_amounts(text)  # safety net on any $ figure
            text = fix_articles(text)                    # #11: a/an correction
            if stripped:
                flags.append(
                    f"stripped a dollar amount from {lead.company}'s line — never state a figure"
                )
        # Multi-signal ("double"): a hire-primary lead that ALSO raised — mention
        # both. The raise stays code-templated (honest, never a dollar amount).
        if pack.funding_phrase is not None and _has_funding_signal(lead, pack.raise_signals):
            raise_txt = pack.funding_phrase(lead)
            text = f"{text} and {raise_txt}" if text else raise_txt

    # A magnet lead's date is when a DOCUMENT was filed, not when the situation
    # arose. "runs 3 funds with no outside administrator, about a week ago"
    # attaches the date to the wrong noun and implies the arrangement is new.
    if with_date and is_magnet_lead(lead):
        with_date = False
    if with_date:                              # follow-ups pass False (Option A):
        suffix = date_suffix(lead, today)      # they send days later, so a baked-in
        if suffix:                             # relative date would drift by send time.
            text = f"{text}, {suffix}" if text else suffix

    loc = city_display(lead.city) or state_display(lead.state)
    said = spoken_name(lead.company)          # "Antilles Power Depot, Inc." -> no "Inc."
    line = f"{said}, {loc}: {text}" if loc else f"{said}: {text}"

    if not lead.is_findable:
        flags.append(f"unfindable lead ({lead.company}) — google the name to confirm it's real")
    if lead.name_cut_off:
        flags.append(
            f"name cut off by the source ({lead.company}: \"{lead.name_cut_off}\") — "
            "check the real name before sending"
        )
    if lead.name_glued:
        flags.append(
            f"name may be missing a space ({lead.company}: \"{lead.name_glued}\") — "
            "check the registered name before sending"
        )
    if is_raise(lead, pack.raise_signals) and geo_level == "city":
        flags.append(
            f"funding lead ({lead.company}) drives a city claim — its city may be "
            "a registered address, not HQ"
        )
    return line, flags


def build_email_1(
    gift: Gift,
    prospect: Prospect,
    *,
    today: date,
    pack=None,
    include_signoff: bool = True,
) -> EmailDraft:
    """Render Email #1. EVERY lead line is code-templated (hiring, breach,
    funding) — no model writes any part of a sent email. The scaffolding is
    niche-blind; `pack` (default CFO) supplies subject/framing/left-field/CTA
    voice and the raise/priority-signal knobs.

    `include_signoff=False` (the platform send path, B4a) omits the trailing
    'best, ishaan' so Smartlead's per-mailbox signature owns the signoff."""
    pack = pack or default_pack()
    flags: list[str] = []
    subject = build_subject(gift, prospect, pack=pack)
    record = record_opener(gift, prospect)
    framing = record[0] if record else pack.framing(gift, prospect)

    lines: list[str] = []
    numbered = gift.gift_size >= 2                     # 5d: 1 lead folds in, no numbers
    for i, lead in enumerate(gift.leads):
        # `_lead_line` still runs for a record gift: its flags (unfindable,
        # cut-off name) hold whichever text the line ends up printing.
        line, lf = _lead_line(lead, today, gift.geo_level, pack=pack)
        flags.extend(lf)
        if record:
            line = record[1][i]
        lines.append(f"{i + 1}. {line}" if numbered else line)

    left_field = left_field_for(pack, gift)
    cta = pack.cta(gift, prospect)
    # lowercase prose, proper nouns intact: "hey dora," not "hey Dora,".
    # Kept on purpose (2026-10-25): the user tried the email without it and it
    # read abrupt.
    greeting = f"hey {(prospect.first_name or 'there').lower()},"

    # B4a: on the platform send path the signoff is owned by each Smartlead
    # mailbox's signature field ("best, mason" etc.), so the copy engine adds
    # NONE — otherwise the send gets a double signoff. include_signoff stays
    # True for the legacy Airtable-review flow (m4_walkthrough).
    parts = [greeting, framing, "\n".join(lines), left_field, cta]
    if include_signoff:
        parts.append("best,\nishaan")
    body = strip_em_dashes("\n\n".join(parts))     # house style: no em dashes anywhere
    subject = strip_em_dashes(subject)
    # The same scrub over the same two parts, so this is an exact suffix of
    # `body` rather than a reconstruction that could drift from it.
    shared_tail = strip_em_dashes("\n\n".join([left_field, cta]))

    # 5e / Step-10 copy flag when a priority-signal lead is present.
    if (
        pack.priority_signal and pack.priority_flag
        and any(lead.signal_type == pack.priority_signal for lead in gift.leads)
    ):
        flags.append(pack.priority_flag)

    return EmailDraft(subject=subject, body=body, flags=flags,
                      shared_tail=shared_tail)


def _followup_qualifier(lead: Lead, prospect: Prospect) -> str:
    """An HONEST qualifier for a follow-up lead ("dental practice ", "in denver
    ", ...), used only when the lead genuinely matches that facet of the
    prospect. Empty when nothing matches, so we never imply a relationship that
    isn't there.

    The niche branch goes through `niche_noun` like every other niche mention in
    the copy. Returning the bare LABEL rendered "found one more healthcare
    showing the same signal" — a missing noun, and only on the niche path, which
    is the path rank 1-3 prospects take. The best emails in every run carried
    it. `niche_noun` also fixes the labels that are not adjectives at all:
    "nonprofit" -> "nonprofit", "legal" -> "law firm"."""
    lvl = compute_match_level(lead, prospect)
    if prospect.classification == "niched" and lvl is not None and lvl <= 3:
        niche = niche_display(prospect.match_param)
        if niche:
            return f"{niche_noun(niche, 1)} "
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    same_state = bool(prospect.state and lead.state
                      and state_display(lead.state) == state)
    if city and same_state and lead.city and city_display(lead.city) == city:
        return f"in {city} "
    if state and lead.state and state_display(lead.state) == state:
        return f"in {state} "
    return ""


# Email #3 pivots off leads entirely.
#
# Emails 1 and 2 already gifted four companies. A fifth changes nothing for a
# reader who ignored the first four, because by then it is the PREMISE that is
# wrong for them ("you are short on leads"), not the quantity — and no amount of
# restating a wrong premise fixes it. So the last email drops the gift and asks
# what their bottleneck actually is.
#
# That question is also the only one whose answer is a conversation rather than
# a subscription, which is the whole point: the leads were never the product,
# they were the proof that the person asking can build things. "worth 15 min?"
# keeps the sequence's single ask intact — every step points at the same call.
#
# It takes no lead, so `_followup_drafts` consumes none for this step.
#
# 2026-10-24: it ended "...i'd be curious what it is. worth a look?", a
# question about a bottleneck followed by an ask about a tool. It now ends on
# the question itself.
_FINAL_PIVOT = (
    "last one from me.\n\n"
    "no worries if leads aren't what you're short on. i build custom tools, so "
    "if something else is draining your week, what is it?"
)


# Email 2 for an inventory record (2026-10-24): one plain sentence in email 1's
# own words, no "showing the same signal" jargon. It arrives in email 1's
# thread, so "found" and "offer still stands" were saying nothing.
#
#   one more in atlanta: Warrior Alliance had weak financial controls flagged
#   in its federal audit, two years in a row.
#
#   worth a look? happy to set it up for you either way.
_FOLLOWUP_TAIL = "worth a look? happy to set it up for you either way."


def _record_predicate(lead: Lead) -> str | None:
    """What one record lead did, as a predicate ("had ... flagged ..."), or
    None when it has no sentence form (the caller keeps the colon line)."""
    t = lead.signal_type
    p = _payload(lead)
    if t in DUTIES:
        return DUTIES[t].sentence(lead)
    if t == NONPROFIT_SIGNAL:
        facts = _audit_facts(lead)
        if facts is None:
            phrase = nonprofit_phrase(lead)
            if phrase.startswith("filed their federal audit"):
                return phrase.replace("their", "its", 1)
            if phrase == "their next federal audit isn't on file":
                # Absence on the clearinghouse only: an agency can grant an
                # extension, so never "missed" or "late".
                return "doesn't have its next federal audit on file yet"
            return None
        what, repeat = facts
        said = ("had weak financial controls flagged in its federal audit"
                if what == "controls" else "had its grant handling flagged in its federal audit")
        return said + (", two years in a row" if repeat else "")
    if t == DAVIS_BACON_SIGNAL:
        n = p.get("awards_in_window")
        several = isinstance(n, int) and n > 1
        if p.get("first_contract_on_record"):
            return ("won its first federal construction jobs on record" if several
                    else "won its first federal construction job on record")
        return "won federal construction jobs" if several else "won a federal construction job"
    if t == COST_CONTRACT_SIGNAL:
        kind = p.get("pricing_kind")
        if kind in ("time-and-materials", "labor-hour"):
            return "won an hourly federal contract where the hours can be audited"
        if kind == "cost-reimbursement":
            return "won a federal contract where every cost can be audited"
        return "won a federal contract the government can audit"
    if t == FIRST_GRANT_SIGNAL:
        return "got its first federal grant in 3+ years"
    if t == NEW_LICENSE_SIGNAL:
        where = _elsewhere(lead, _licensing_state(lead))
        if p.get("formed_class") == "new_company":
            return f"is a new contracting company, just licensed{where}"
        return f"just got a contractor license{where}"
    if t == LICENSE_UPGRADE_SIGNAL:
        return license_upgrade_phrase(lead)
    if t == NEW_BUSINESS_SIGNAL:
        return new_business_phrase(lead)
    return None


def _record_followup(lead: Lead, prospect: Prospect) -> str | None:
    """Email 2's core for a record lead, or None to keep the old shape."""
    said = _record_predicate(lead)
    if said is None:
        return None
    name = spoken_name(lead.company)
    city, state = city_display(prospect.city), state_display(prospect.state)
    lead_city, lead_state = city_display(lead.city), state_display(lead.state)
    if city and lead_city == city and lead_state and lead_state == state:
        first = f"one more in {city}: {name} {said}."
    elif state and lead_state == state:
        at = f" in {lead_city}" if lead_city else ""
        first = f"one more in {state}: {name}{at} {said}."
    else:
        at = f" in {lead_city or lead_state}" if (lead_city or lead_state) else ""
        first = f"one more: {name}{at} {said}."
    return f"{first}\n\n{_FOLLOWUP_TAIL}"


def build_followup_email(
    lead: Lead | None,
    prospect: Prospect,
    *,
    step: int,
    today: date,
    pack=None,
    include_signoff: bool = False,
    gift_signals: frozenset[str] | set[str] | None = None,
) -> EmailDraft:
    """Email #2 / #3 (B3, B4). Threaded under Email #1, so the SUBJECT IS BLANK
    (Smartlead sends a blank-subject step as a reply on the same thread).

    Email #2 has two shapes:
      * value    — a genuinely NEW lead surfaced (`lead` given): one honest lead
                   line + the same binary ask Email #1 makes.
      * fallback — no new lead (`lead is None`): a light bump, no fabricated lead.

    `gift_signals` (email 1's signal types) decides whether email 2 may say
    "showing the same signal"; None keeps the old wording.

    Email #3 (step 3) is ALWAYS `_FINAL_PIVOT`: no lead, no gift, one question
    about their real bottleneck. `lead` is accepted and ignored there so the
    signature stays uniform for callers that still pass one.

    Honesty is identical to Email #1: dates only for high-confidence signals,
    raises templated with no dollar figure, all via `_lead_line`. Signoff is
    owned by the Smartlead mailbox signature (B4a) → default include_signoff=False."""
    if step not in (2, 3):
        raise ValueError(f"follow-up step must be 2 or 3, got {step!r}")
    pack = pack or default_pack()
    flags: list[str] = []
    final = step == 3

    if final:
        core = _FINAL_PIVOT
    elif lead is not None and (record := _record_followup(lead, prospect)) is not None:
        # `_lead_line` still runs for its flags (unfindable, cut-off name).
        flags.extend(_lead_line(lead, today, "none", pack=pack, with_date=False)[1])
        core = record
    elif lead is not None:
        line, lf = _lead_line(lead, today, "none", pack=pack, with_date=False)
        flags.extend(lf)
        qual = _followup_qualifier(lead, prospect)
        # "the same signal" only when it IS email 1's signal. A follow-up lead
        # can be another kind (a new business filling a construction gift),
        # and claiming sameness then is a small false claim the recipient can
        # check against the email above it.
        same = gift_signals is None or lead.signal_type in gift_signals
        if same:
            opener = f"found one more {qual}showing the same signal:"
        elif lead.signal_type in _RECORD_FAMILY:
            opener = f"found one more {qual}from public records:"
        else:
            opener = f"found one more {qual}worth sharing:"
        # The tail asks for the same thing email #1 did. The old one ("want me
        # to keep sending these?") recruited a subscriber, which is the wrong
        # yes: a sequence whose steps chase different outcomes converts on the
        # easiest one, and that was never the call.
        tail = "offer still stands on setting it up for you. worth a look?"
        core = f"{opener}\n\n{line}\n\n{tail}"
        if pack.priority_signal and lead.signal_type == pack.priority_signal and pack.priority_flag:
            flags.append(pack.priority_flag)
    else:
        niche = niche_claim_or_geo(prospect)
        sig = pack.followup_signal
        core = (
            f"circling back, still keeping an eye out for {niche_noun(niche)} "
            f"showing {sig}. worth a look?"
        )

    parts = [core]
    if include_signoff:
        parts.append("best,\nishaan")
    body = strip_em_dashes("\n\n".join(parts))     # house style: no em dashes anywhere
    return EmailDraft(subject="", body=body, flags=flags)


def niche_claim_or_geo(prospect: Prospect) -> str:
    """Bare descriptor for the fallback follow-up ('dental', 'denver', or a
    neutral default) — no lead to anchor a claim, so keep it soft/geographic."""
    if prospect.classification == "niched":
        niche = niche_display(prospect.match_param)
        if niche:
            return niche
    return city_display(prospect.city) or state_display(prospect.state) or "these kinds of"
