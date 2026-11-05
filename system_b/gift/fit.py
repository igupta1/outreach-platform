"""Gate B — genuine value_prop fit check (the honest gate).

System A assigns each lead a coarse industry tag, and it is sometimes WRONG
(an IT/defense firm bucketed `manufacturing`). Tier 1/2 make an explicit claim
— "you work with [niche] companies, here's a [niche] company" — so trusting the
tag alone lets a false claim through. Before a niche is claimed, this asks an
LLM whether each gift lead's value_prop genuinely READS as that niche. Code
enforces the gate (resolver drops the tier unless every gift lead passes); the
LLM only judges fit, it can't introduce a claim. Injectable so tests stay
offline and deterministic.
"""

from __future__ import annotations

import json

from system_b.models import Lead

_SYSTEM = (
    "You verify whether companies genuinely operate in a given industry — an "
    "honesty check before a cold email claims the recipient works with that "
    "industry. You get an industry label and, for each company, its name, any "
    "official industry code or label from a government record (NAICS, SIC, "
    "NTEE, Medicare provider type, license type), and a note. The note often "
    "describes a legal filing or deadline, not what the business does: judge "
    "the industry from the name and the official codes, and use the note only "
    "if it describes the business. For EACH company, answer fits=true ONLY if "
    "the name, code or description clearly places it in that industry; answer "
    "false if they point to a different industry or nothing shows the "
    "industry. Be strict: vague or adjacent is false. "
    'Return JSON {"verdicts": [{"id": "...", "fits": true|false}]}.'
)

# Payload fields that say what the business IS, from the record itself.
_CODE_FIELDS = (
    ("naics_description", "NAICS"), ("naics_title", "NAICS"), ("naics_label", "NAICS"),
    ("sic_description", "SIC"), ("ntee_industry", "NTEE"),
    ("provider_type_text", "Medicare provider type"), ("provider_type", "provider type"),
    ("omig_provider_type", "Medicaid provider type"), ("grantee_type", "grantee type"),
    ("license_type", "license type"), ("specialty", "license specialty"),
    ("industry_type", "industry"), ("industry_group", "industry"),
)


# Official NAICS titles (2022), most specific first, for records that carry a
# bare code (Form 5500, H-2B): the model does not reliably read "621111" as
# a doctor's office and rejected it as "can't tell".
NAICS_TITLES: dict[str, str] = {
    "5411": "Legal Services", "5412": "Accounting, Tax Preparation, Bookkeeping, and Payroll Services",
    "5413": "Architectural, Engineering, and Related Services", "5415": "Computer Systems Design",
    "5416": "Management, Scientific, and Technical Consulting Services", "5418": "Advertising and Public Relations",
    "6211": "Offices of Physicians", "6212": "Offices of Dentists", "6213": "Offices of Other Health Practitioners",
    "6214": "Outpatient Care Centers", "6216": "Home Health Care Services", "5419": "Other Professional Services",
    "111": "Crop Production", "112": "Animal Production", "211": "Oil and Gas Extraction",
    "221": "Utilities", "236": "Construction of Buildings", "237": "Heavy and Civil Engineering Construction",
    "238": "Specialty Trade Contractors", "311": "Food Manufacturing", "312": "Beverage and Tobacco Manufacturing",
    "325": "Chemical Manufacturing", "332": "Fabricated Metal Product Manufacturing", "333": "Machinery Manufacturing",
    "334": "Computer and Electronic Product Manufacturing", "336": "Transportation Equipment Manufacturing",
    "339": "Miscellaneous Manufacturing", "423": "Merchant Wholesalers, Durable Goods",
    "424": "Merchant Wholesalers, Nondurable Goods", "441": "Motor Vehicle and Parts Dealers",
    "445": "Food and Beverage Retailers", "455": "General Merchandise Retailers", "456": "Health and Personal Care Retailers",
    "484": "Truck Transportation", "492": "Couriers and Messengers", "493": "Warehousing and Storage",
    "511": "Publishing Industries", "512": "Motion Picture and Sound Recording Industries", "513": "Publishing Industries",
    "518": "Computing Infrastructure, Data Processing, Web Hosting", "522": "Credit Intermediation and Related Activities",
    "523": "Securities, Commodity Contracts, Investments", "524": "Insurance Carriers and Related Activities",
    "525": "Funds, Trusts, and Other Financial Vehicles", "531": "Real Estate", "532": "Rental and Leasing Services",
    "541": "Professional, Scientific, and Technical Services", "551": "Management of Companies and Enterprises",
    "561": "Administrative and Support Services", "562": "Waste Management and Remediation Services",
    "611": "Educational Services", "621": "Ambulatory Health Care Services", "622": "Hospitals",
    "623": "Nursing and Residential Care Facilities", "624": "Social Assistance",
    "711": "Performing Arts, Spectator Sports", "713": "Amusement, Gambling, and Recreation Industries",
    "721": "Accommodation", "722": "Food Services and Drinking Places", "811": "Repair and Maintenance",
    "812": "Personal and Laundry Services", "813": "Religious, Grantmaking, Civic, Professional, and Similar Organizations",
    "11": "Agriculture, Forestry, Fishing and Hunting", "21": "Mining, Quarrying, and Oil and Gas Extraction",
    "22": "Utilities", "23": "Construction", "31": "Manufacturing", "32": "Manufacturing", "33": "Manufacturing",
    "42": "Wholesale Trade", "44": "Retail Trade", "45": "Retail Trade", "48": "Transportation and Warehousing",
    "49": "Transportation and Warehousing", "51": "Information", "52": "Finance and Insurance",
    "53": "Real Estate and Rental and Leasing", "54": "Professional, Scientific, and Technical Services",
    "55": "Management of Companies", "56": "Administrative and Support Services", "61": "Educational Services",
    "62": "Health Care and Social Assistance", "71": "Arts, Entertainment, and Recreation",
    "72": "Accommodation and Food Services", "81": "Other Services", "92": "Public Administration",
}


def naics_title(code: object) -> str:
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    for n in (4, 3, 2):
        if len(digits) >= n and digits[:n] in NAICS_TITLES:
            return NAICS_TITLES[digits[:n]]
    return ""


def official_industry(lead: Lead) -> str:
    """What the lead's own records say its business is ("NAICS 722511 Full-
    Service Restaurants; license type: ..."), or "" when they say nothing.

    The fit check used to read only `value_prop`, which for the legal-duty
    leads explains the filing ("Late participant contributions are generally
    corrected by...") and says nothing of the business, so the strict check
    answered "can't tell" and good leads failed (2026-11-04: Hollings,
    healthcare, rejected four times over)."""
    parts: list[str] = []
    for sig in lead.signals[:3]:
        p = sig.payload or {}
        code = p.get("naics") or p.get("sic") or p.get("ntee_code")
        for key, label in _CODE_FIELDS:
            v = p.get(key)
            if isinstance(v, str) and v.strip():
                text = f"{label}: {v.strip()}"
                if label in ("NAICS", "SIC", "NTEE") and code:
                    text = f"{label} {code} {v.strip()}"
                if text not in parts:
                    parts.append(text)
        if not any(x.startswith(("NAICS", "SIC")) for x in parts) and p.get("naics"):
            title = naics_title(p["naics"])
            parts.append(f"NAICS {p['naics']}" + (f" ({title})" if title else ""))
    return "; ".join(parts[:4])


def fit_check(niche_label: str, leads: list[Lead], *, model: str = "gpt-4o") -> list[bool]:
    """Per-lead booleans (aligned with `leads`): does each lead's value_prop
    genuinely read as a `niche_label` company? Missing/omitted leads default to
    False (strict — never claim fit we didn't get)."""
    if not leads:
        return []

    from openai import OpenAI

    from system_b import config

    config.require("OPENAI_API_KEY")
    client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=60)

    items = [
        {"id": lead.id, "company": lead.company,
         "official_industry": official_industry(lead), "note": lead.value_prop or ""}
        for lead in leads
    ]
    user = f"industry label: {niche_label}\ncompanies: {json.dumps(items)}"
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
    )
    data = json.loads(resp.choices[0].message.content or "{}")
    by_id: dict[str, bool] = {}
    for v in data.get("verdicts", []):
        if isinstance(v, dict) and v.get("id") is not None:
            by_id[str(v["id"])] = bool(v.get("fits"))
    return [by_id.get(lead.id, False) for lead in leads]


_CLAIM_SYSTEM = (
    "A cold email is about to tell a bookkeeping / accounting / CFO firm "
    "\"noticed you work with <industry>\". You get the exact phrase from the "
    "firm's own website that the claim rests on. Such phrases are usually an "
    "item from an \"industries we serve\" list (\"Construction & Contractors\", "
    "\"Mass Tort\", \"Biotech Startup\") or a line about who the firm helps "
    "(\"Real Estate Accounting\" = accounting FOR real estate; \"construction "
    "bookkeeping\" = bookkeeping FOR construction). Answer serves=true when the "
    "phrase names that industry (or a clear part of it) as who the firm works "
    "for. Answer false only if the phrase is about the firm's OWN services with "
    "no client industry (\"Specialized consulting for investors\" does not "
    "make its clients consulting firms), its background or a past employer "
    "(\"advisory and audit firm BDO\"), software it sells or uses, a different "
    "industry that shares a word (insurance brokerage is not real estate "
    "brokerage), or names no industry at all (\"deal structuring\", \"cultural "
    "leaders\"). The other phrases the site lists are context: a phrase among "
    "several industries (\"Construction\", \"Restaurants\", \"CPA & Tax Firms\") "
    "is an industry the firm serves. "
    'Return JSON {"serves": true|false}.'
)
_CLAIMS: dict[tuple[str, str, str], bool] = {}


def claim_check(phrase: str, niche_label: str, listed: tuple[str, ...] = (), *,
                model: str = "gpt-4o") -> bool:
    """Does the firm's own phrase say it serves `niche_label` clients?

    Gate B checked only the LEADS; nothing checked the claim against the
    words it rests on. Mapping is keyword matching, so on 2026-11-04 it drafted
    "you work with real estate brokerage companies" off "Commercial Insurance
    Brokerage", "professional services" off "advisory and audit firm BDO" (a
    past employer) and "consulting firms" off "Specialized consulting for
    investors" (the firm's own service). False on any failure: no answer, no
    claim."""
    key = ((phrase or "").strip().lower(), (niche_label or "").strip().lower(),
           "|".join(x.strip().lower() for x in listed))
    if not all(key[:2]):
        return False
    if key in _CLAIMS:
        return _CLAIMS[key]
    try:
        from openai import OpenAI

        from system_b import config

        config.require("OPENAI_API_KEY")
        client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=60)
        resp = client.chat.completions.create(
            model=model, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": _CLAIM_SYSTEM},
                      {"role": "user", "content": json.dumps(
                          {"industry": niche_label, "phrase": phrase,
                           "every_phrase_the_site_lists": list(listed)})}],
        )
        ok = bool(json.loads(resp.choices[0].message.content or "{}").get("serves"))
    except Exception:  # noqa: BLE001 — no answer, no claim
        return False
    _CLAIMS[key] = ok
    return ok
