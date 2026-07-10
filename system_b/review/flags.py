"""Step 10 auto-flags — every caveat that needs a human eyeball, computed
from the gift + prospect + research + draft. These are the review gate that
holds the "not embarrassing" floor before anything can be approved to send.
"""

from __future__ import annotations

import re

from system_b.gift.models import Gift, Prospect

# Local imports kept lazy-free; engine is pure.
from system_b.gift.engine import compute_match_level  # noqa: F401  (kept for parity/use)

# --- A1: non-destructive domain-mismatch flag --------------------------------
# System A can mis-resolve a company to an unrelated brand's domain (Poaster
# Technologies -> warp.co), attaching the wrong value_prop. We can't safely
# DROP on a string mismatch (acronyms, spelling variants, and branded domains
# are false positives), so instead we conservatively FLAG only gross mismatches
# for a human google. Errs toward "matches" to keep the flag meaningful.

_GENERIC_WORDS = frozenset({
    "inc", "llc", "corp", "corporation", "co", "company", "ltd", "limited",
    "group", "holdings", "technologies", "technology", "tech", "solutions",
    "services", "systems", "labs", "global", "international", "the", "and",
    "partners", "ventures", "capital", "enterprises",
})
_STOP_WORDS = frozenset({"for", "of", "the", "and", "a", "an", "to"})
# Entity/legal suffixes — excluded from the acronym so "Community Foundation
# Partnership, Inc." -> "cfp" (matches cfpartner.org), not "cfpi".
_ENTITY_SUFFIXES = frozenset({
    "inc", "incorporated", "llc", "corp", "corporation", "ltd", "limited",
    "co", "pa", "pc", "lp", "llp", "plc",
})


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _is_subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(c in it for c in short)


def domain_matches_company(company: str, domain: str | None) -> bool:
    """Conservative match — True unless `domain` grossly fails to relate to
    `company`. Tolerates acronyms (cviga.org for Center for the Visually
    Impaired), variants (herrmanglobal for Herrmann), and vowel-drops
    (ghst.io for Ghost); only unrelated brands (warp.co for Poaster) fail."""
    if not domain:
        return True
    root = domain.lower().split(".")[0]
    if not root:
        return True
    words = re.findall(r"[a-z0-9]+", company.lower())
    content = [w for w in words if w not in _GENERIC_WORDS and len(w) >= 2]
    if not content:
        return True  # all-generic name -> can't judge
    for t in content:
        if len(t) >= 3 and (t in root or root in t):
            return True
    acr = [w for w in words if w not in _STOP_WORDS and w not in _ENTITY_SUFFIXES and len(w) >= 2]
    initials = "".join(w[0] for w in acr)
    if len(initials) >= 2 and (root.startswith(initials) or initials.startswith(root)):
        return True
    for t in content:
        if _common_prefix_len(t, root) >= 4:
            return True
        if len(root) >= 3 and _is_subsequence(root, t):
            return True
    return False


def review_flags(prospect: Prospect, gift: Gift, research=None, draft=None) -> list[str]:
    """The ordered, de-duplicated flag list for a queued item."""
    flags: list[str] = []

    def add(f: str) -> None:
        if f not in flags:
            flags.append(f)

    # From research: thin website, unmapped niche, client-list presence-only.
    if research is not None:
        for f in research.flags:
            add(f)

    # cfo_wanted / low-confidence date -> mandatory live-posting check.
    if any(l.signal_type == "cfo_wanted" for l in gift.leads):
        add("cfo_wanted / low-confidence lead present — MANDATORY: google the "
            "posting and confirm it's still live (copy carries no date)")

    # The niche came from the LLM classifier -> spot-check value_prop.
    if prospect.classification == "niched":
        add("niche is LLM-classified — glance at each lead's value_prop: does it "
            "actually match the claimed niche?")

    # Client-list source is presence-only. Research already emits this flag;
    # only add our own if it isn't already covered (avoids a near-dupe).
    if prospect.niche_source == "client_list" and not any("presence-only" in f for f in flags):
        add("client-list niche is presence-only — verify these are real clients "
            "(not logos / partners) and SMBs")

    # Per-lead caveats.
    for l in gift.leads:
        if not l.niche or l.niche == "unknown":
            add(f"null-niche lead ({l.company}) — matched by geography only")
        if l.domain is None:
            add(f"domainless lead ({l.company}) — google the name to confirm it's real")
        elif not domain_matches_company(l.company, l.domain):
            add(f"domain {l.domain} may not belong to {l.company} — verify the "
                "value_prop describes the right company (possible mis-resolution)")
        if l.signal_type in ("funding_only", "double_signal") and gift.geo_level == "city":
            add(f"funding lead ({l.company}) drives a city claim — its city may be "
                "a registered address, not HQ")
        if l.signal_type == "double_signal":
            add(f"double_signal lead ({l.company}) — sanity-check both signals are "
                "the same company")
        if l.finance_grade == "weak":
            add(f"weak finance_grade lead ({l.company}) used")
        if l.freshness == "stale":
            add(f"stale lead ({l.company}) used")

    # Gift shape.
    if gift.gift_size < 3:
        add(f"gift has only {gift.gift_size} lead(s) (3 is best)")
    if gift.subject_shape == "plural" and not gift.all_niche and gift.geo_level == "none":
        add('bare "companies" subject (weakest) — consider pulling more/closer leads')

    # Copy-layer: a dollar amount was stripped from a raise line.
    if draft is not None:
        for f in draft.flags:
            if "dollar amount" in f:
                add(f)

    return flags
