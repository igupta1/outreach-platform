"""Which voice a prospect gets when their site does not say which service they
sell. Every prospect comes from an Apollo finance-firm list, so such a firm is
no longer held (`no_rung`): its ONE list picks the pack, and several lists or
none get the neutral "finance firms" voice. No network: research and the gift
are stubbed."""

from __future__ import annotations

from datetime import date

import pytest

from system_b.copy.email import DAVIS_BACON_SIGNAL
from system_b.gift.models import Gift, Prospect
from system_b.prospects import row_from_apollo
from system_b.sequence.generate import choose_voice
from system_b.tests.test_gift import FakeScraper, mk

TODAY = date(2026, 10, 19)

# The words each rung's voice uses for its buyer. A neutral draft says none.
RUNG_WORDS = ("bookkeeper", "accountant", "cfo")


class _Research:
    def __init__(self, rung):
        self.rung = rung
        self.rung_evidence = ()
        self.candidate_phrases = ()
        self.evidence = ()
        self.flags = ()


def _draft(monkeypatch, *, rung, source, pack_key="cfo", force_pack=False):
    import system_b.sequence.generate as gen

    leads = [mk(f"l{i}", DAVIS_BACON_SIGNAL, city="Denver", state="CO",
                company=f"Builder {i}") for i in range(5)]
    prospect = Prospect(firm_name="Acme", city="Denver", state="CO",
                        classification="generalist", first_name="dana")
    gift = Gift(leads=leads[:3], best_lead=leads[0], gift_size=3, all_niche=False,
                geo_level="city", subject_shape="plural", what_category="davis_bacon",
                best_lead_level=1)
    spare = list(leads[3:])

    def one_more(p, sc, *, target=3, niche_only=False, pack=None):
        if not spare:
            return None
        ld = spare.pop(0)
        return Gift(leads=[ld], best_lead=ld, gift_size=1, all_niche=False,
                    geo_level="city", subject_shape="singular",
                    what_category="davis_bacon", best_lead_level=1)

    monkeypatch.setattr(gen, "research_prospect", lambda *a, **k: _Research(rung))
    monkeypatch.setattr(gen, "resolve_gift", lambda research, row, sc, pack=None: (prospect, gift))
    monkeypatch.setattr(gen, "build_gift", one_more)
    row = {"firm_name": "Acme", "website": "http://a.com", "email": "d@acme.com",
           "city": "Denver", "state": "CO", "first_name": "dana", "_source": source}
    return gen.generate_sequence(row, FakeScraper([]), {}, TODAY,
                                 pack_key=pack_key, force_pack=force_pack)


def _copy(res) -> str:
    return " ".join(res[k] for k in ("subject", "email_1", "email_2", "email_3",
                                     "li_dm_1", "li_dm_1_evergreen", "li_dm_2")).lower()


@pytest.mark.parametrize("source, pack, audience", [
    ("FractionalCFO", "cfo", "fractional cfos"),
    ("Accounting", "accounting", "accountants"),
    ("Bookkeeping", "bookkeeping", "bookkeepers"),
])
def test_one_apollo_list_picks_the_voice_when_the_site_is_silent(
        monkeypatch, source, pack, audience):
    res = _draft(monkeypatch, rung=None, source=source)
    assert res["status"] == "ok"
    assert res["pack"] == pack and res["voice_source"] == "apollo list"
    assert f"this one is for {audience}." in res["email_1"]
    assert f"built this one for {audience}." in res["li_dm_1"]
    card = res["review"]
    assert (card["voice"], card["voice_source"], card["apollo_lists"]) == \
        (pack, "apollo list", source)


@pytest.mark.parametrize("source", [
    "FractionalCFO+Accounting", "Accounting+Bookkeeping",
    "FractionalCFO+Accounting+Bookkeeping", "", None,
])
def test_several_lists_or_none_get_the_neutral_voice(monkeypatch, source):
    """Never calls a CPA a bookkeeper: the neutral draft names no rung at all."""
    res = _draft(monkeypatch, rung=None, source=source)
    assert res["status"] == "ok"
    assert res["pack"] == "finance" and res["voice_source"] == "neutral"
    assert "this one is for finance firms." in res["email_1"]
    assert "built this one for finance firms." in res["li_dm_1"]
    copy = _copy(res)
    assert not [w for w in RUNG_WORDS if w in copy], copy
    assert res["review"]["voice_source"] == "neutral"


def test_the_site_still_wins_over_the_apollo_list(monkeypatch):
    res = _draft(monkeypatch, rung="bookkeeping", source="Accounting")
    assert (res["pack"], res["voice_source"]) == ("bookkeeping", "site")
    assert "this one is for bookkeepers." in res["email_1"]


def test_force_pack_overrides_site_and_list(monkeypatch):
    res = _draft(monkeypatch, rung="bookkeeping", source="Accounting",
                 pack_key="cfo", force_pack=True)
    assert (res["pack"], res["voice_source"]) == ("cfo", "forced")
    res = _draft(monkeypatch, rung=None, source="FractionalCFO+Accounting",
                 pack_key="accounting", force_pack=True)
    assert (res["pack"], res["voice_source"]) == ("accounting", "forced")


def test_choose_voice_reads_list_names_loosely():
    assert choose_voice(None, " fractionalcfo ") == ("cfo", "apollo list")
    # The same list twice is still one list.
    assert choose_voice(None, "Bookkeeping+Bookkeeping") == ("bookkeeping", "apollo list")
    # A list that is not a finance-firm list picks nothing.
    assert choose_voice(None, "Lawyers") == ("finance", "neutral")


def test_the_apollo_list_reaches_the_prospect_row():
    row = row_from_apollo({"Website": "acme.com", "Email": "d@acme.com",
                           "Company Name": "Acme", "_source": "FractionalCFO+Accounting"})
    assert row["_source"] == "FractionalCFO+Accounting"
    assert row_from_apollo({"Website": "acme.com", "Email": "d@acme.com"})["_source"] == ""
