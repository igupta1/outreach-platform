"""The 990 filing-gap types (2026-10-29, `copy.duty.HELD_DUTIES`): worded but
HELD -- no gift, opener, subject or DM can use one until the user approves
(`gift.engine.HELD_TYPES`, and the inventory's APPROVED_SIGNALS leaves them
out). The words are checked by rendering them with the hold lifted
(OUTREACH_PREVIEW_HELD=1) in a separate interpreter, so this process keeps
the live vocabulary."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from system_b.copy.duty import DUTIES, HELD_DUTIES
from system_b.copy.email import MAGNET_SIGNALS, RECORD_SIGNALS
from system_b.gift.engine import HELD_TYPES, TYPE_ORDER
from system_b.gift.engine import MAGNET_SIGNALS as ENGINE_MAGNET

GAPS = ("nonprofit_990_missed_1yr", "nonprofit_990_missed_2yr")
ROOT = Path(__file__).resolve().parents[2]


def test_the_gap_types_are_worded_but_held_everywhere():
    assert set(GAPS) <= set(HELD_DUTIES) and set(GAPS) <= HELD_TYPES
    for t in GAPS:
        assert t not in DUTIES and t not in RECORD_SIGNALS and t not in MAGNET_SIGNALS
        assert t not in ENGINE_MAGNET
        assert t in TYPE_ORDER                 # its rank is ready for the day it is approved
    # Two years outranks one; both sit with the "required report missing" kinds.
    assert TYPE_ORDER["nonprofit_990_missed_2yr"] < TYPE_ORDER["nonprofit_single_audit_late"] \
        < TYPE_ORDER["nonprofit_990_missed_1yr"] < TYPE_ORDER["nonprofit_exemption_revoked"]


def test_the_inventory_holds_them_too():
    inv = Path.home() / "Developer/Inventory/leadinv/sources.py"
    if not inv.exists():
        pytest.skip("no inventory checkout")
    tree = ast.parse(inv.read_text())

    def tuple_named(name):
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", "") == name for t in n.targets))
        return {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    assert set(GAPS) <= tuple_named("NONPROFIT_DUTY_SIGNALS")
    assert not set(GAPS) & tuple_named("APPROVED_SIGNALS")


_PREVIEW = r"""
import json
from datetime import date
from system_b.copy.duty import DUTIES
from system_b.copy.email import _RECORD_WHY, build_email_1, build_followup_email, magnet_phrase, record_opener
from system_b.copy.linkedin import build_dm_1_evergreen
from system_b.copy.subject import short_subject
from system_b.gift.engine import _cfo_what_category
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead, Signal
from system_b.niches.base import pack_for

def lead(t, name, years, near):
    return Lead(id=f"{t}:{name}", company=name, city="Denver", state="CO", industry="nonprofit",
                signal_type=t, entity_id=f"ein:{name}",
                signals=[Signal(type=t, date="2025-11-17", date_confidence="medium",
                                plain_words_description="IRS public records show no FY2024 Form 990.",
                                source_url="https://projects.propublica.org/nonprofits/organizations/1",
                                payload={"missed_tax_years": years, "next_deadline_within_90_days": near})])

def gift(leads):
    return Gift(leads=leads, best_lead=leads[0], gift_size=len(leads), all_niche=False,
                geo_level="city", subject_shape="singular" if len(leads) == 1 else "plural",
                what_category=_cfo_what_category(leads), best_lead_level=1)

p = Prospect(firm_name="Ledger Books", city="Denver", state="CO", first_name="Dana")
pack = pack_for("cfo")
LONGEST = max(len(a[0]) + 2 + len(b[0]) for a, b in _RECORD_WHY.values())
out = {"longest": LONGEST}
for t, years in (("nonprofit_990_missed_1yr", [2024]), ("nonprofit_990_missed_2yr", [2023, 2024])):
    three = gift([lead(t, n, years, near) for n, near in
                  (("Mile High Youth Fund", True), ("Front Range Arts Inc", False),
                   ("Colorado Food Bank Network", False))])
    one = gift([lead(t, "Mile High Youth Fund", years, True)])
    d = DUTIES[t]
    e1 = build_email_1(three, p, today=date(2026, 10, 29), pack=pack, include_signoff=False)
    e2 = build_followup_email(three.leads[0], p, step=2, today=date(2026, 10, 29), pack=pack,
                              gift_signals={t})
    out[t] = {"opener": record_opener(three, p), "opener_one": record_opener(one, p),
              "email_1": e1.body, "subject": e1.subject, "short": short_subject(three, p),
              "email_2": e2.body, "line": magnet_phrase(three.leads[0]),
              "dm": build_dm_1_evergreen(three, p, pack=pack),
              "pred_why": len(d.generic_plural()) + 2 + len(d.why_for(three.leads))}
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def preview():
    env = {**os.environ, "OUTREACH_PREVIEW_HELD": "1"}
    res = subprocess.run([sys.executable, "-c", _PREVIEW], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_two_years_renders_exactly_in_the_record_opener_format(preview):
    framing, lines = preview["nonprofit_990_missed_2yr"]["opener"]
    assert framing.endswith("these 3 nonprofits in denver have no 990 on irs public record for "
                            "two years running, so a third would cost each its tax exemption:")
    assert lines == ["Mile High Youth Fund (fy2023 and fy2024, next one due soon)",
                     "Front Range Arts (fy2023 and fy2024)",
                     "Colorado Food Bank Network (fy2023 and fy2024)"]
    assert preview["nonprofit_990_missed_2yr"]["opener_one"][0].endswith(
        "this nonprofit in denver has no 990 on irs public record for two years running, so a "
        "third would cost it its tax exemption:")


def test_one_year_renders_exactly(preview):
    framing, lines = preview["nonprofit_990_missed_1yr"]["opener"]
    assert framing.endswith("these 3 nonprofits in denver have no 990 on irs public record for "
                            "a year past due, and three years running costs a charity its "
                            "exemption:")
    assert lines[0] == "Mile High Youth Fund (fy2024, next one due soon)"
    assert lines[1] == "Front Range Arts (fy2024)"


@pytest.mark.parametrize("t", GAPS)
def test_held_wording_keeps_every_record_rule(preview, t):
    r = preview[t]
    assert r["pred_why"] <= preview["longest"]
    assert len(r["line"].split()) <= 8 and len(r["line"]) <= 54
    for text in (r["email_1"], r["subject"], r["short"], r["email_2"], r["dm"] or "", r["line"]):
        low = text.lower()
        assert "—" not in text and "$" not in text and "None" not in text, text
        for w in ("missed", "failed", "violat", "delinquent", "illegal", "didn't file"):
            assert w not in low, (w, text)
        assert "irs public records show" not in low          # never the raw evidence
    assert r["short"].startswith("3 denver nonprofits with no 990 on file")
    assert r["email_2"].startswith("one more in denver: Mile High Youth Fund has no 990 on irs "
                                   "public record")
