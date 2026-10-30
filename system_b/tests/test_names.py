"""The model may change how a lead's name is written, never which name it is
(copy/names.py). Offline: the model is a fake."""

from __future__ import annotations

from system_b.copy.names import NameFixer, same_name
from system_b.models import Lead, Signal


def test_same_name_accepts_what_the_first_200_batch_needed():
    for original, fixed in [
        ("Vip Structures", "VIP Structures"),
        ("Kla Roofing & Construction", "KLA Roofing & Construction"),
        ("Refugee Support Services Of Thecarolinas", "Refugee Support Services of the Carolinas"),
        ("N B C-U S A Of New York One Housing Development Fund",
         "NBC-USA of New York One Housing Development Fund"),
        ("Foundation For University Hospital A New Jersey Nonprofit Co",
         "Foundation for University Hospital"),
        ("Meadows Mental Health Policy Institute For Tex, The",
         "The Meadows Mental Health Policy Institute for Texas"),
        ("Solid Ground Gen CNTRCTNG", "Solid Ground General Contracting"),
        ("Calvin L Wadsworth Construction Company Limited Liability Company",
         "Calvin L Wadsworth Construction"),
        ("Community Link Programs Of Traveler Aid Society Of Central Carolinas I",
         "Community Link Programs of Traveler Aid Society of Central Carolinas"),
        ("Marketumbrella Org", "Marketumbrella"),
        # The three the first run refused, all correct.
        ("12Angels Construction LLC", "12 Angels Construction"),
        ("Mansa LLP", "Mansa"),
        ("Refugee Support Services Of Thecarolinas Inc",
         "Refugee Support Services Of The Carolinas"),
    ]:
        assert same_name(original, fixed), (original, fixed)


def test_same_name_refuses_another_name():
    for original, fixed in [
        ("Vip Structures", "Vip Builders"),                       # a word swapped
        ("Panhandle Regional Advisory Council Trauma Service Area A",
         "Panhandle Regional Advisory Council"),                  # real words cut
        ("Acme Roofing Inc", "Acme Roofing LLC"),                 # a legal form invented
        ("Hope Atlanta", "Hope Atlanta Foundation"),              # a word added
        ("Ladder Up", ""),
    ]:
        assert not same_name(original, fixed), (original, fixed)


def _lead(name: str) -> Lead:
    return Lead(id=name, company=name, signal_type="nonprofit_grant_no_finance_officer",
                signals=[Signal(type="nonprofit_grant_no_finance_officer", date="2026-10-01")])


def test_tidy_renames_in_place_notes_each_change_and_asks_once(tmp_path):
    calls: list[list[str]] = []

    def fake(names: list[str]) -> dict[str, str]:
        calls.append(names)
        return {"Vip Structures": "VIP Structures", "Ladder Up": "Ladder Up",
                "Hope Atlanta": "Hope Atlanta Foundation"}

    fixer = NameFixer(fake, cache_path=tmp_path / "names.json")
    leads = [_lead("Vip Structures"), _lead("Ladder Up"), _lead("Hope Atlanta")]
    notes = fixer.tidy(leads)
    assert [ld.company for ld in leads] == ["VIP Structures", "Ladder Up", "Hope Atlanta"]
    assert any('"Vip Structures" -> "VIP Structures"' in n for n in notes)
    assert any("Hope Atlanta Foundation" in n and "not the same name" in n for n in notes)
    assert len(calls) == 1

    # The same organization in the next firm's gift: no new call, same note.
    again = [_lead("Vip Structures")]
    assert fixer.tidy(again) and again[0].company == "VIP Structures"
    # A lead object already renamed (shared across firms) keeps its note.
    assert fixer.tidy(leads[:1]) == [n for n in notes if "VIP" in n]
    assert len(calls) == 1

    # Tomorrow's run reads today's answers from the cache.
    tomorrow = NameFixer(lambda names: (_ for _ in ()).throw(AssertionError("called")),
                         cache_path=tmp_path / "names.json")
    lead = _lead("Vip Structures")
    tomorrow.tidy([lead])
    assert lead.company == "VIP Structures"


def test_a_failed_model_call_keeps_every_name_as_written(tmp_path):
    def broken(names):
        raise RuntimeError("api down")

    fixer = NameFixer(broken, cache_path=tmp_path / "names.json")
    lead = _lead("Vip Structures")
    assert fixer.tidy([lead]) == [] and lead.company == "Vip Structures"


def test_a_tidied_name_is_what_the_email_prints(monkeypatch, tmp_path):
    from datetime import date

    import system_b.sequence.generate as gen
    from system_b.copy.email import DAVIS_BACON_SIGNAL
    from system_b.gift.models import Gift, Prospect
    from system_b.tests.test_gift import FakeScraper, mk

    leads = [mk(f"l{i}", DAVIS_BACON_SIGNAL, city="Denver", state="CO",
                company=name) for i, name in enumerate(
                    ["Vip Structures", "Kla Roofing", "Acme Builders", "Avm Contractors"])]
    prospect = Prospect(firm_name="Acme CPA", city="Denver", state="CO",
                        classification="generalist", first_name="dana")
    gift = Gift(leads=leads[:3], best_lead=leads[0], gift_size=3, all_niche=False,
                geo_level="city", subject_shape="plural", what_category="davis_bacon",
                best_lead_level=1)

    class R:
        rung, rung_evidence, candidate_phrases, evidence, flags = "accounting", (), (), (), ()

    monkeypatch.setattr(gen, "research_prospect", lambda *a, **k: R())
    monkeypatch.setattr(gen, "resolve_gift", lambda research, row, sc, pack=None: (prospect, gift))
    monkeypatch.setattr(gen, "build_gift", lambda p, sc, **k: Gift(
        leads=[leads[3]], best_lead=leads[3], gift_size=1, all_niche=False, geo_level="city",
        subject_shape="singular", what_category="davis_bacon", best_lead_level=1))
    fixer = NameFixer(lambda names: {n: n.replace("Vip", "VIP").replace("Kla", "KLA")
                                     .replace("Avm", "AVM") for n in names},
                      cache_path=tmp_path / "n.json")
    row = {"firm_name": "Acme CPA", "website": "http://a.com", "email": "d@a.com",
           "city": "Denver", "state": "CO", "first_name": "dana", "_source": "Accounting"}
    res = gen.generate_sequence(row, FakeScraper([]), {}, date(2026, 10, 26),
                                name_fixer=fixer)
    assert "VIP Structures" in res["email_1"] and "KLA Roofing" in res["email_1"]
    assert "Vip" not in res["email_1"] and "AVM Contractors" in res["email_2"]
    assert any('"Avm Contractors" -> "AVM Contractors"' in f for f in res["review"]["flags"])


def test_dropping_only_a_legal_form_is_not_noted(tmp_path):
    fixer = NameFixer(lambda names: {"Warrior Alliance Inc": "Warrior Alliance"},
                      cache_path=tmp_path / "n.json")
    lead = _lead("Warrior Alliance Inc")
    assert fixer.tidy([lead]) == [] and lead.company == "Warrior Alliance"


def test_new_instructions_reask_names_the_old_ones_left_alone(tmp_path):
    import json

    from system_b.copy import names as names_mod

    path = tmp_path / "n.json"
    path.write_text(json.dumps({
        "Rac Construction & Engineering": {"out": "Rac Construction & Engineering",
                                           "status": "unchanged"},
        "Vip Structures": {"out": "VIP Structures", "status": "fixed"}}))
    asked: list[list[str]] = []

    def fake(names):
        asked.append(names)
        return {"Rac Construction & Engineering": "RAC Construction & Engineering"}
    fixer = NameFixer(fake, cache_path=path)
    assert names_mod.PROMPT_VERSION >= 2
    assert fixer("Rac Construction & Engineering") == "RAC Construction & Engineering"
    assert fixer("Vip Structures") == "VIP Structures"     # a kept fix is not re-asked
    assert asked == [["Rac Construction & Engineering"]]


def test_a_trailing_the_moves_to_the_front_in_code():
    from system_b.clients.inventory import _clean_company_name
    from system_b.copy.names import front_the

    assert front_the("San Francisco Housing Accelerator Fund, The") == \
        "The San Francisco Housing Accelerator Fund"
    assert front_the("The Arc") == "The Arc" and front_the(", The") == ", The"
    assert _clean_company_name("San Francisco Housing Accelerator Fund, The") == \
        "The San Francisco Housing Accelerator Fund"


def test_the_keeps_its_place_and_an_apostrophe_joins_a_word():
    from system_b.copy.names import front_the

    assert not same_name("The San Francisco Housing Accelerator Fund",
                         "San Francisco Housing Accelerator Fund, The")
    assert same_name("San Francisco Housing Accelerator Fund, The",
                     "The San Francisco Housing Accelerator Fund")
    assert same_name("Stamford Museum And Nature Center, Inc. The",
                     "The Stamford Museum and Nature Center")
    assert front_the("Stamford Museum And Nature Center, Inc. The") == \
        "The Stamford Museum And Nature Center, Inc"
    assert same_name("Childrens Initiative", "Children's Initiative")
    assert same_name("Adults & Childrens Alliance Inc", "Adults & Children’s Alliance")
    assert same_name("The Treehouse A Childrens Acad", "The Treehouse A Children's Academy")
    assert not same_name("Childrens Initiative", "Children's Health Initiative")


def test_a_cached_fix_the_guard_now_refuses_is_undone(tmp_path):
    import json

    path = tmp_path / "n.json"
    path.write_text(json.dumps({
        "The San Francisco Housing Accelerator Fund": {
            "out": "San Francisco Housing Accelerator Fund, The", "status": "fixed"},
        "San Francisco Housing Accelerator Fund, The": {
            "out": "San Francisco Housing Accelerator Fund, The", "status": "unchanged", "v": 2}}))
    fixer = NameFixer(None, cache_path=path)
    a, b = _lead("The San Francisco Housing Accelerator Fund"), \
        _lead("San Francisco Housing Accelerator Fund, The")
    fixer.tidy([a, b])
    assert a.company == b.company == "The San Francisco Housing Accelerator Fund"
