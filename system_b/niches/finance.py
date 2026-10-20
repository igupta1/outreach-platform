"""The NEUTRAL finance pack: for a firm whose rung we do not know.

Every prospect comes from an Apollo finance-firm list, so a site that never
says which service it sells is still a finance firm; it is just not knowable
which KIND. Before this pack such a firm was held (`no_rung`). Now its voice
comes from the Apollo list it was pulled from, and when that is ambiguous too
(several lists, or none) it gets this pack, which names nobody's rung:
"built this one for finance firms". Calling a CPA a bookkeeper reads as not
having looked; "finance firms" is true of all three.

Everything else is the CFO pack's, whose subject, framing and need clause
already say "finance help" rather than any rung's word. The one CFO-specific
knob, the fractional-CFO posting as the lead-first signal, is switched off:
that ranks a gift by what a CFO buys.
"""

from __future__ import annotations

from dataclasses import replace

from system_b.niches.cfo import CFO_PACK

FINANCE_PACK = replace(
    CFO_PACK,
    key="finance",
    priority_signal=None,
    dm_audience="finance firms",
)
