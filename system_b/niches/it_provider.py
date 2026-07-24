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

from system_b.copy.email import _cta, _funding_phrase, framing_line
from system_b.copy.subject import build_who_what
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead
from system_b.niches.base import NichePack

_LEFT_FIELD_LABELS: tuple[str, ...] = ("A", "B", "C", "D", "E")


# MSP — managed IT / help desk -------------------------------------------------

_MSP_SINGULAR_WHAT = {
    "job_it_support": (
        "that just posted an it support role",
        "that's hiring for it support",
        "that just opened an it support seat",
    ),
    "job_it_leadership": (
        "that just posted an it leadership role",
        "that's hiring it leadership",
        "that just opened an it leadership seat",
    ),
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


MSP_LEFT_FIELD: tuple[str, ...] = (
    "most msps i talk to say clients come by referral, till the pipeline slows. "
    "built this to catch companies the week they start hiring for it support.",
    "every msp i talk to says the same thing, the best clients are the ones who "
    "just realized they need help. so i built a feed that catches them the day they "
    "post an it support role.",
    "most it shops i know wait for the referral. built this to surface companies the "
    "moment they post their first help desk hire.",
    "the msps i talk to say the hire-vs-outsource moment is the whole game. so i "
    "built a feed that flags companies right when they post an it role.",
    "most msps i talk to say timing is everything. built this to catch companies the "
    "week an it-support need shows up.",
)


# MSSP — managed security ------------------------------------------------------

MSSP_PRIORITY_FLAG = (
    "breach_disclosed lead present — confirm the disclosure is real and current "
    "before sending, and keep the line soft (no specifics on the breach)"
)

_MSSP_SINGULAR_WHAT = {
    "breach_disclosed": (
        "that just disclosed a breach",
        "that just reported a breach",
        "that just had a security incident",
    ),
    "job_security": (
        "that just started hiring for security",
        "that's staffing up on security",
        "that just opened a security role",
    ),
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


MSSP_LEFT_FIELD: tuple[str, ...] = (
    "most mssps i talk to say the best clients are the ones who just realized "
    "security is on them now. built this to catch companies the week they start "
    "staffing it.",
    "every security shop i talk to says the same thing, the opening is the moment a "
    "company decides it needs help. so i built a feed that catches them the day they "
    "post a security role.",
    "most mssps i know hear about a breach long after the fact. built this to surface "
    "companies the moment they signal a security need.",
    "the security providers i talk to say a fresh breach disclosure or a security req "
    "is the opening. so i built a feed that flags exactly those.",
    "most mssps i talk to say timing is everything in security. built this to catch "
    "companies the week a security-need signal shows up.",
)


# Cloud — cloud / devops consultancy -------------------------------------------

_CLOUD_SINGULAR_WHAT = {
    "job_cloud_devops": (
        "that just started building out cloud",
        "that's staffing up on cloud",
        "that just opened a cloud/devops role",
    ),
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


CLOUD_LEFT_FIELD: tuple[str, ...] = (
    "most cloud shops i talk to say clients come by referral, till it slows. built "
    "this to catch companies the week they start building out devops.",
    "every cloud consultant i talk to says the same thing, the best clients are the "
    "ones just starting to scale. so i built a feed that catches them the day they "
    "post a devops role.",
    "most devops shops i know wait for the referral. built this to surface companies "
    "the moment they post their first cloud hire.",
    "the cloud consultants i talk to say the build-vs-outsource moment is the whole "
    "game. so i built a feed that flags companies right when they post devops roles.",
    "most cloud shops i talk to say timing is everything. built this to catch "
    "companies the week a cloud-need signal shows up.",
)


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
    left_field=MSP_LEFT_FIELD,
    left_field_labels=_LEFT_FIELD_LABELS,
    funding_phrase=None,
    priority_flag=None,
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
    left_field=MSSP_LEFT_FIELD,
    left_field_labels=_LEFT_FIELD_LABELS,
    funding_phrase=None,
    priority_flag=MSSP_PRIORITY_FLAG,
)

CLOUD_PACK = NichePack(
    key="cloud",
    followup_signal="a cloud-need signal",
    signal_rank={"job_cloud_devops": 0, "funding_form_d": 1},
    priority_signal=None,
    raise_signals=frozenset({"funding_form_d"}),   # a raise line is templated (no $)
    what_category=_cloud_what_category,
    subject=_cloud_subject,
    framing=_cloud_framing,
    cta=_cta,
    left_field=CLOUD_LEFT_FIELD,
    left_field_labels=_LEFT_FIELD_LABELS,
    funding_phrase=_funding_phrase,
    priority_flag=None,
)
