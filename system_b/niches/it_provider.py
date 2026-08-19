"""IT-provider niche packs — MSP, MSSP, and Cloud/DevOps.

Three buyers, one shape. Each is an outsourced IT services firm that wins on
timing: a company that just showed a signal in its lane is a company weighing
build-vs-outsource, i.e. the moment to reach out.

  * MSP  (managed IT / help desk): companies posting an IT-support or IT-leadership role.
  * MSSP (managed security):       companies that disclosed a breach, or posted a
                                   security role.
  * Cloud (cloud/devops shop):     companies posting cloud/devops roles (a fresh
                                   raise is a close secondary — money to build with).

The copy is VERTICAL-AWARE with a geo fallback: it claims the firm's served
vertical only when the prospect is `niched` (via the shared `niche_claim` gate in
the copy scaffolding), otherwise it opens on the prospect's city/state. Adaptation
of leadgen inventory rows onto the outreach `Lead` lives in `clients/inventory.py`.
"""

from __future__ import annotations

from system_b.copy.email import _cta, framing_line
from system_b.copy.subject import build_who_what
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead
from system_b.niches.base import NichePack



# MSP — managed IT / help desk -------------------------------------------------

_MSP_SINGULAR_WHAT = {
    "job_it_support": "that just posted an it support role",
    "job_it_leadership": "that just posted an it leadership role",
}


def _msp_subject(gift: Gift, prospect: Prospect) -> str:
    singular = _MSP_SINGULAR_WHAT.get(gift.best_lead.signal_type, "that just posted an it role")
    return build_who_what(
        gift, prospect,
        singular_what=singular,
        plural_what="staffing up on it right now",
    )


def _msp_framing(gift: Gift, prospect: Prospect) -> str:
    return framing_line(
        gift, prospect,
        need="looking for it help right now",
    )


def _msp_what_category(leads: list[Lead]) -> str:
    return "it_support"




# MSSP — managed security ------------------------------------------------------

MSSP_PRIORITY_FLAG = (
    "breach_disclosed lead present — confirm the disclosure is real and current "
    "before sending, and keep the line soft (no specifics on the breach)"
)

_MSSP_SINGULAR_WHAT = {
    "breach_disclosed": "that just disclosed a breach",
    "job_security": "that just started hiring for security",
}


def _mssp_subject(gift: Gift, prospect: Prospect) -> str:
    singular = _MSSP_SINGULAR_WHAT.get(gift.best_lead.signal_type, "that just signaled a security need")
    return build_who_what(
        gift, prospect,
        singular_what=singular,
        plural_what="signaling they need security help right now",
    )


def _mssp_framing(gift: Gift, prospect: Prospect) -> str:
    return framing_line(gift, prospect, need="looking for security help right now")


def _mssp_what_category(leads: list[Lead]) -> str:
    return "security"




# Cloud — cloud / devops consultancy -------------------------------------------

_CLOUD_SINGULAR_WHAT = {
    "job_cloud_devops": "that just started building out cloud",
    "funding_form_d": ("that just raised", "that just closed a round", "that just landed funding"),
}


def _cloud_subject(gift: Gift, prospect: Prospect) -> str:
    singular = _CLOUD_SINGULAR_WHAT.get(gift.best_lead.signal_type, "that just started building out cloud")
    return build_who_what(
        gift, prospect,
        singular_what=singular,
        plural_what="scaling their cloud team right now",
    )


def _cloud_framing(gift: Gift, prospect: Prospect) -> str:
    return framing_line(gift, prospect, need="looking for cloud help right now")


def _cloud_what_category(leads: list[Lead]) -> str:
    return "cloud"




MSP_PACK = NichePack(
    key="msp",
    followup_signal="an it-need signal",
    signal_rank={"job_it_support": 0, "job_it_leadership": 0},
    priority_signal=None,             # geo-matched, no lead-first signal
    raise_signals=frozenset(),        # no raises → lead lines use the plain description
    what_category=_msp_what_category,
    subject=_msp_subject,
    framing=_msp_framing,
    cta=_cta,
    funding_phrase=None,
    priority_flag=None,
    dm_audience="msps",
    dm_role_singular="an it role",
    dm_role_plural="it roles",
)

MSSP_PACK = NichePack(
    key="mssp",
    followup_signal="a security-need signal",
    signal_rank={"breach_disclosed": 0, "job_security": 1},
    priority_signal="breach_disclosed",   # a disclosed breach is the lead-first signal
    raise_signals=frozenset(),
    what_category=_mssp_what_category,
    subject=_mssp_subject,
    framing=_mssp_framing,
    cta=_cta,
    funding_phrase=None,
    priority_flag=MSSP_PRIORITY_FLAG,
    dm_audience="mssps",
    dm_role_singular="a security role",
    dm_role_plural="security roles",
)

CLOUD_PACK = NichePack(
    key="cloud",
    followup_signal="a cloud-need signal",
    signal_rank={"job_cloud_devops": 0, "funding_form_d": 1},
    priority_signal=None,
    raise_signals=frozenset(),   # EDGAR sources deleted — no raise claim is provable
    what_category=_cloud_what_category,
    subject=_cloud_subject,
    framing=_cloud_framing,
    cta=_cta,
    funding_phrase=None,
    priority_flag=None,
    dm_audience="cloud shops",
    dm_role_singular="a cloud role",
    dm_role_plural="cloud roles",
)
