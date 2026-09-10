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
from system_b.copy.subject import build_subject, niche_claim
from system_b.gift.engine import compute_match_level
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead
from system_b.niches.base import default_pack
from system_b.niches.text import noun

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
LEFT_FIELD = (
    "i'm an engineer. i build these lead systems, and this one is for "
    "{audience}."
)


def left_field_for(pack) -> str:
    """The 5b line for a pack. `dm_audience` already names the buyer the way the
    copy says it aloud ("fractional cfos", "bookkeepers"), so the packs need no
    second field for it."""
    return LEFT_FIELD.format(audience=pack.dm_audience)


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
    companies = noun(n, "company", "companies")

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
    companies = noun(n, "company", "companies")
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
    companies = noun(n, "company", "companies")
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
_CTA_LINE = (
    "still tuning it. worth a look? happy to set it up to run for you either "
    "way :)"
)


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

NONPROFIT_SIGNAL = "nonprofit_grant_no_finance_officer"
FUNDS_SIGNAL = "adv_no_fund_administrator"
ECOMMERCE_SIGNAL = "ecommerce_sku_load_no_finance_staff"

MAGNET_SIGNALS = frozenset({NONPROFIT_SIGNAL, FUNDS_SIGNAL, ECOMMERCE_SIGNAL})


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


def magnet_phrase(lead: Lead) -> str:
    """The templated line for a magnet lead."""
    return {
        NONPROFIT_SIGNAL: nonprofit_phrase,
        FUNDS_SIGNAL: funds_phrase,
        ECOMMERCE_SIGNAL: ecommerce_phrase,
    }[lead.signal_type](lead)


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
    framing = pack.framing(gift, prospect)

    lines: list[str] = []
    numbered = gift.gift_size >= 2                     # 5d: 1 lead folds in, no numbers
    for i, lead in enumerate(gift.leads):
        line, lf = _lead_line(lead, today, gift.geo_level, pack=pack)
        flags.extend(lf)
        lines.append(f"{i + 1}. {line}" if numbered else line)

    left_field = left_field_for(pack)
    cta = pack.cta(gift, prospect)
    # lowercase prose, proper nouns intact: "hey dora," not "hey Dora,".
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
    if city and lead.city and city_display(lead.city) == city:
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
_FINAL_PIVOT = (
    "last one from me.\n\n"
    "no worries if leads aren't what you're short on. i build custom tools, so "
    "if something else is draining your week i'd be curious what it is. "
    "worth a look?"
)


def build_followup_email(
    lead: Lead | None,
    prospect: Prospect,
    *,
    step: int,
    today: date,
    pack=None,
    include_signoff: bool = False,
) -> EmailDraft:
    """Email #2 / #3 (B3, B4). Threaded under Email #1, so the SUBJECT IS BLANK
    (Smartlead sends a blank-subject step as a reply on the same thread).

    Email #2 has two shapes:
      * value    — a genuinely NEW lead surfaced (`lead` given): one honest lead
                   line + the same binary ask Email #1 makes.
      * fallback — no new lead (`lead is None`): a light bump, no fabricated lead.

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
    elif lead is not None:
        line, lf = _lead_line(lead, today, "none", pack=pack, with_date=False)
        flags.extend(lf)
        qual = _followup_qualifier(lead, prospect)
        opener = f"found one more {qual}showing the same signal:"
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
