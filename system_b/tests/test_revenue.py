"""The revenue personalization lever: parsing (research/revenue.py) and
rendering (copy/lex.revenue_display).

Every phrase marked "real" below was pulled verbatim from a live prospect site
during the 102-site measurement that justified building this at all (23% state a
usable range, vs 1% who state a headcount criterion).

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_revenue.py -q
"""

from __future__ import annotations

from system_b.copy.lex import revenue_display
from system_b.research.revenue import parse_revenue_range

M = 1_000_000


def test_parses_every_real_range_seen_in_the_wild():
    cases = {
        "$2M–$50M revenue": (2 * M, 50 * M),
        "$2M–$10M in revenue but you can’t tell which jobs make money": (2 * M, 10 * M),
        "Serving CEOs of companies with $1M-$10M in annual revenue": (1 * M, 10 * M),
        "companies from $2M to $50M in revenue": (2 * M, 50 * M),
        "For most businesses with annual revenue below $50 million": (None, 50 * M),
        "ecommerce owners doing $1M+: we’ll 2x your profit in 60 days": (1 * M, None),
        "Established Small to Midsize Businesses ($5M+ Revenue)": (5 * M, None),
    }
    for phrase, want in cases.items():
        assert parse_revenue_range(phrase) == want, phrase


def test_lower_bound_inherits_the_unit_from_the_upper():
    """Real phrasing writes the unit once: "$1-$30m" means one MILLION to
    thirty million. Without inheritance the low end parses as one dollar and the
    range is nonsense."""
    assert parse_revenue_range("Helping CEOs doing $1-$30m in revenue scale") == (1 * M, 30 * M)


def test_open_ended_upper_bound_is_not_a_ceiling():
    """"$2M to $50M+" means 2M and up. Recording 50M as a max would understate
    what they told us."""
    assert parse_revenue_range("generating $2M to $50M+ in revenue") == (2 * M, None)


def test_rejects_the_firms_own_track_record():
    """The prompt tells the model not to offer these, but a number headed for a
    sent email is the wrong place to trust a model. "$360M+ Raised by our
    clients" parses as a clean $360m+ range and would tell a solo fractional CFO
    they work with $360M companies."""
    for phrase in (
        "$360M+ Raised by our clients",
        "we’ve saved clients $2M",
        "Clients Supported (25+)",
        "$1.2B in assets under management",
        "we have managed over $40M for our customers",
    ):
        assert parse_revenue_range(phrase) is None, phrase


def test_rejects_implausible_and_unreadable_figures():
    assert parse_revenue_range("plans from $99 to $499 a month") is None   # a price
    assert parse_revenue_range("we work with small businesses") is None     # no figure
    assert parse_revenue_range("") is None
    assert parse_revenue_range(None) is None


def test_rejects_a_backwards_range():
    assert parse_revenue_range("$50M-$2M in revenue") is None


def test_display_reads_as_a_modifier_in_front_of_companies():
    assert revenue_display((2 * M, 10 * M)) == "$2m-$10m"
    assert revenue_display((1 * M, None)) == "$1m+"
    assert revenue_display((None, 50 * M)) == "sub-$50m"
    assert revenue_display((2_500_000, 10 * M)) == "$2.5m-$10m"
    assert revenue_display((500_000, 5 * M)) == "$500k-$5m"
    assert revenue_display(None) == ""
