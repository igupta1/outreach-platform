"""Gift engine — Steps 2b + 3 of the spec (pure logic, no infra)."""

from system_b.gift.engine import build_gift, compute_match_level, pull_one_lead
from system_b.gift.models import Gift, Prospect
from system_b.gift.taxonomy import map_prospect

__all__ = [
    "build_gift",
    "compute_match_level",
    "pull_one_lead",
    "map_prospect",
    "Gift",
    "Prospect",
]
