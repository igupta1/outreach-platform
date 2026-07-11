"""Site-based niche auto-detection for the insurance-agency router and the
recruiter pack. Fetch is injected, so these run offline."""

from __future__ import annotations

from system_b.niches import insurance_agency as router
from system_b.niches.recruiter import detect_function, detect_function_from_site


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


# --- recruiter function ----------------------------------------------------

def test_detect_function() -> None:
    assert detect_function("we are a finance recruiting firm placing controllers") == "finance"
    assert detect_function("technical recruiting and software talent") == "engineering"
    assert detect_function("cybersecurity recruiting specialists") == "security"
    assert detect_function("we place great people everywhere") is None       # generalist


def test_detect_function_from_site_injected() -> None:
    site = _fake_site("Sales recruiting and gtm talent for saas companies.")
    assert detect_function_from_site("http://x", fetch=site) == "sales"


def test_detect_function_fetch_failure_is_generalist() -> None:
    def boom(url: str):
        raise RuntimeError("down")
    assert detect_function_from_site("http://x", fetch=boom) is None
