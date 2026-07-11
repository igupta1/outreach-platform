"""Site-based niche auto-detection for the insurance-agency router.
Fetch is injected, so these run offline."""

from __future__ import annotations

from system_b.niches import insurance_agency as router


def _fake_site(text: str):
    def fetch(url: str) -> dict[str, str]:
        return {url: text}
    return fetch


# --- insurance-agency sub-niche -------------------------------------------

def test_detect_subniche_trucking() -> None:
    site = _fake_site("We insure motor carriers and commercial fleets across the midwest.")
    assert router.detect_subniche_from_site("http://x", fetch=site) == "trucking"


def test_detect_subniche_pc_default() -> None:
    site = _fake_site("General liability, workers comp, and BOP coverage for small businesses.")
    assert router.detect_subniche_from_site("http://x", fetch=site) == "pc"


def test_detect_subniche_fetch_failure_defaults_pc() -> None:
    def boom(url: str):
        raise RuntimeError("down")
    assert router.detect_subniche_from_site("http://x", fetch=boom) == "pc"
