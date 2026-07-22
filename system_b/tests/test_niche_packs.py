"""The five niche packs — their signal vocabulary knobs, and that the gift
engine ranks a gift by the ACTIVE pack's `signal_rank`.

`pack_for(key)` resolves each of the five packs (accounting, cfo, mssp, msp,
cloud). Every buyer-specific knob lives in the pack; here we pin down each
pack's `signal_rank`/`priority_signal`, then prove `build_gift(..., pack=...)`
picks the best lead by that pack's rank (rank beats recency, as in test_gift's
confluence example).

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_niche_packs.py -q
"""

from __future__ import annotations

import pytest

from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.niches.base import pack_for
from system_b.niches.cfo import CFO_PACK
from system_b.niches.it_provider import MSSP_PACK
from system_b.tests.test_gift import FakeScraper, mk


# --------------------------------------------------------------------------
# Each pack's signal vocabulary (signal_rank + priority_signal).
# --------------------------------------------------------------------------

# (key) -> (expected signal_rank, expected priority_signal)
EXPECTED_PACKS = {
    "cfo": (
        {"job_fractional_cfo": 0, "job_finance_lead": 1, "funding_form_d": 2},
        "job_fractional_cfo",
    ),
    "accounting": (
        {"job_finance_lead": 0, "job_junior_finance": 0, "funding_form_d": 1, "funding_form_c": 1},
        None,
    ),
    "mssp": (
        {"breach_disclosed": 0, "job_security": 1},
        "breach_disclosed",
    ),
    "msp": (
        {"job_it_support": 0, "job_it_leadership": 0},
        None,
    ),
    "cloud": (
        {"job_cloud_devops": 0, "funding_form_d": 1},
        None,
    ),
}


@pytest.mark.parametrize("key,expected", EXPECTED_PACKS.items())
def test_pack_signal_rank_and_priority(key, expected):
    expected_rank, expected_priority = expected
    pack = pack_for(key)
    assert pack.key == key
    assert dict(pack.signal_rank) == expected_rank
    assert pack.priority_signal == expected_priority


def test_pack_for_covers_all_five_niches():
    # each of the five leadgen niches resolves to a pack keyed to it
    assert {pack_for(k).key for k in ("accounting", "cfo", "mssp", "msp", "cloud")} == \
        {"accounting", "cfo", "mssp", "msp", "cloud"}


# --------------------------------------------------------------------------
# build_gift ranks a gift by the ACTIVE pack's signal_rank (rank beats recency).
# --------------------------------------------------------------------------

def test_mssp_gift_ranks_breach_over_security():
    # MSSP pack: breach_disclosed (rank 0) outranks job_security (rank 1), even
    # though the security lead is FRESHER — rank beats recency for the best lead.
    p = Prospect(
        firm_name="Sentinel Security", city="Denver", state="CO",
        classification="niched", match_param=("industry", "healthcare"),
    )
    leads = [
        mk("sec", "job_security", industry="healthcare", city="Denver", state="CO", date="2026-07-05"),
        mk("breach", "breach_disclosed", industry="healthcare", city="Denver", state="CO", date="2026-07-01"),
    ]
    g = build_gift(p, FakeScraper(leads), pack=MSSP_PACK)
    assert g is not None
    assert g.best_lead.id == "breach"                        # breach_disclosed (0) > job_security (1)
    assert g.leads[0].id == "breach"                         # and leads the within-level order


def test_cfo_gift_ranks_cfo_wanted_over_finance_lead():
    # CFO pack: job_fractional_cfo (rank 0, the priority signal) outranks
    # job_finance_lead (rank 1), despite being the older lead.
    p = Prospect(
        firm_name="Denver Health CFOs", city="Denver", state="CO",
        classification="niched", match_param=("industry", "healthcare"),
    )
    leads = [
        mk("finance", "job_finance_lead", industry="healthcare", city="Denver", state="CO", date="2026-07-05"),
        mk("cfo", "job_fractional_cfo", industry="healthcare", city="Denver", state="CO", date="2026-07-01"),
    ]
    g = build_gift(p, FakeScraper(leads), pack=CFO_PACK)
    assert g is not None
    assert g.best_lead.id == "cfo"                           # job_fractional_cfo (0) > job_finance_lead (1)
    assert g.leads[0].id == "cfo"


def test_cfo_gift_ranks_finance_lead_over_funding_within_level():
    # Same CFO rank map applied WITHIN a level (no priority-signal lead present):
    # job_finance_lead (rank 1) outranks funding_form_d (rank 2), older wins on rank.
    p = Prospect(
        firm_name="Denver Health CFOs", city="Denver", state="CO",
        classification="niched", match_param=("industry", "healthcare"),
    )
    leads = [
        mk("raise", "funding_form_d", industry="healthcare", city="Denver", state="CO", date="2026-07-05"),
        mk("hire", "job_finance_lead", industry="healthcare", city="Denver", state="CO", date="2026-07-01"),
    ]
    g = build_gift(p, FakeScraper(leads), pack=CFO_PACK)
    assert g is not None
    assert g.best_lead.id == "hire"                          # job_finance_lead (1) > funding_form_d (2)
    assert g.leads[0].id == "hire"
