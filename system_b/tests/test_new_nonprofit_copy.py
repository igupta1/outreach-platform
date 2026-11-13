"""The two new-nonprofit types (Nonprofit `newnp.py`, approved 2026-10-30):
`nonprofit_new_501c3` (a state formation date within 12 months + an IRS
501(c)(3) letter within 6, filing code 01) and `nonprofit_first_990` (the
first annual return, corroborated). Pinned in the record-opener format, and
held to the record: a 990-EZ is named as one (never "full 990"), and the only
no-help claim is "filed without a paid preparer", made only when the return
names no preparer firm AND no preparer (`paid_preparer_listed` is False)."""

from __future__ import annotations

from datetime import date

import pytest

from system_b.copy.duty import DUTIES
from system_b.copy.email import (
    _RECORD_WHY,
    RECORD_SIGNALS,
    build_email_1,
    build_followup_email,
    magnet_phrase,
    record_opener,
)
from system_b.copy.linkedin import build_dm_1_evergreen
from system_b.copy.subject import short_subject
from system_b.gift.engine import HELD_TYPES, TYPE_ORDER, _cfo_what_category
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead, Signal
from system_b.niches.base import pack_for

NEW = ("nonprofit_new_501c3", "nonprofit_first_990")
TODAY = date(2026, 10, 30)
DANA = Prospect(firm_name="Ledger Books", city="Denver", state="CO", first_name="Dana")
NAMES = ("Mile High Youth Fund", "Front Range Arts", "Colorado Food Bank Network")
LONGEST = max(len(p[0]) + 2 + len(w[0]) for p, w in _RECORD_WHY.values())


def lead(t: str, name: str, payload: dict | None = None) -> Lead:
    return Lead(id=f"{t}:{name}", company=name, city="Denver", state="CO",
                industry="nonprofit", signal_type=t, entity_id=f"ein:{name}",
                signals=[Signal(type=t, date="2025-12-31", date_confidence="low",
                                plain_words_description="Filed their first Form 990-EZ ...",
                                source_url="https://projects.propublica.org/nonprofits/x",
                                payload=dict(payload or {}))])


def gift(leads: list[Lead]) -> Gift:
    return Gift(leads=leads, best_lead=leads[0], gift_size=len(leads), all_niche=False,
                geo_level="city", subject_shape="singular" if len(leads) == 1 else "plural",
                what_category=_cfo_what_category(leads), best_lead_level=1)


def body(g: Gift) -> str:
    return build_email_1(g, DANA, today=TODAY, pack=pack_for("cfo"), include_signoff=False).body


def test_both_types_are_live_and_ranked_below_every_duty():
    for t in NEW:
        assert t in DUTIES and t in RECORD_SIGNALS and t not in HELD_TYPES
    # Weaker than any audit, missing return or license: a new nonprofit is
    # not yet in trouble. Row 8 still comes after them.
    assert TYPE_ORDER["construction_new_licensed_business"] < TYPE_ORDER["nonprofit_first_990"] \
        < TYPE_ORDER["nonprofit_new_501c3"] < TYPE_ORDER["new_business_formed"]


def test_new_501c3_renders_exactly():
    g = gift([lead("nonprofit_new_501c3", n) for n in NAMES])
    framing, lines = record_opener(g, DANA)
    assert framing == ("these 3 nonprofits in denver were just approved as nonprofits by the "
                       "irs, so each must file a tax return every year:")
    assert lines == list(NAMES)
    one, _ = record_opener(gift([lead("nonprofit_new_501c3", NAMES[0])]), DANA)
    assert one.endswith("this nonprofit in denver was just approved as a nonprofit by the irs, "
                        "so it must file a tax return every year:")
    assert short_subject(g, DANA) == "3 denver nonprofits newly recognized as 501(c)(3)s"


def test_first_990_names_the_form_and_only_the_preparer_absence_the_return_shows():
    g = gift([lead("nonprofit_first_990", NAMES[0],
                   {"return_type": "990EZ", "tax_year": 2025, "paid_preparer_listed": False}),
              lead("nonprofit_first_990", NAMES[1],
                   {"return_type": "990", "tax_year": 2025, "paid_preparer_listed": True}),
              lead("nonprofit_first_990", NAMES[2],
                   {"return_type": "990EZ", "tax_year": 2026, "paid_preparer_listed": None})])
    framing, lines = record_opener(g, DANA)
    # 2026-11-13, the user: only first returns filed without an accountant
    # reach a gift (clients.inventory._not_a_buyer), so the opener says it once.
    assert framing.endswith("these 3 nonprofits in denver filed their first irs returns "
                            "without an accountant:")
    assert lines == ["Mile High Youth Fund", "Front Range Arts", "Colorado Food Bank Network"]
    assert short_subject(g, DANA) == "3 denver nonprofits that filed their first irs returns"
    e2 = build_followup_email(g.leads[0], DANA, step=2, today=TODAY, pack=pack_for("cfo"),
                              gift_signals={"nonprofit_first_990"})
    assert e2.body.startswith("one more in denver: Mile High Youth Fund filed its first irs "
                              "return without an accountant.")


@pytest.mark.parametrize("t", NEW)
def test_every_record_rule_holds(t):
    payload = {"return_type": "990EZ", "tax_year": 2025, "paid_preparer_listed": False}
    three = gift([lead(t, n, payload) for n in NAMES])
    d = DUTIES[t]
    assert len(d.generic_plural()) + 2 + len(d.why_for(three.leads)) <= LONGEST
    line = magnet_phrase(three.leads[0])
    assert len(line.split()) <= 8 and len(line) <= 54
    e1 = build_email_1(three, DANA, today=TODAY, pack=pack_for("cfo"), include_signoff=False)
    texts = [e1.subject, e1.body, line, build_dm_1_evergreen(three, DANA, pack=pack_for("cfo"))
             or ""]
    for text in texts:
        low = text.lower()
        assert "—" not in text and "$" not in text and "None" not in text, text
        for w in ("full 990", "brand new", "just started", "no accountant", "no finance",
                  "failed", "missed", "violat"):
            assert w not in low, (w, text)
    # The engineer line calls charities organizations.


def test_a_first_990_with_a_preparer_is_not_a_lead():
    from datetime import date

    from system_b.clients.inventory import _not_a_buyer
    today = date(2026, 11, 13)
    with_cpa = lead("nonprofit_first_990", "A", {"paid_preparer_listed": True})
    alone = lead("nonprofit_first_990", "B", {"paid_preparer_listed": False})
    with_cpa.signals[0].date = alone.signals[0].date = "2026-10-01"
    assert _not_a_buyer({}, with_cpa, today) == "has_a_preparer"
    assert _not_a_buyer({}, alone, today) is None
