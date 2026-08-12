"""An advisory read of the finished copy: which phrases don't sound like a person.

Everything else in `copy/` is deterministic, and this does not change that. The
model is never given the pen — it returns SPANS it thinks read as machine-written
plus a short reason, and code keeps only the spans. Nothing it says can alter a
sent email; the worst it can do is put a line on the review card that the
operator ignores.

That distinction is the whole design. A model that rewrites copy would break the
rule the rest of the system is built on ("no model writes any part of a sent
email"), and it would do so invisibly — the wrong word would ship looking exactly
like the right one.

## Why it is allowed to be quiet

The review gate already carries honesty flags, and those are stop-signs: a
domainless lead, an unverified client list. These are suggestions. If the check
fired on every card it would bury the stop-signs, so the prompt is told to return
nothing when the copy reads fine and the result is capped. A quiet check is a
useful one.

## Three guards

* **Verbatim.** A returned span must appear character-for-character in the copy
  or it is dropped. Same discipline as Gate A: the model can only point AT the
  text, never introduce text. A hallucinated quote would send the operator
  hunting for a phrase that is not there.
* **Capped.** At most `_MAX_ISSUES`, so one talkative response cannot turn a
  clean card into a wall of advice.
* **Non-fatal.** Any failure returns no issues. The run is not worth losing over
  an advisory read, and a missing suggestion costs nothing that the operator's
  own eyes do not already cover.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

log = logging.getLogger("system_b.naturalness")

# More than a few suggestions on one card is noise, and it crowds out the
# honesty flags, which are the ones that actually stop a send.
_MAX_ISSUES = 3

_SYSTEM = (
    "You are proofreading ONE cold email for defects a RECIPIENT would notice. "
    "The writer is a software engineer emailing a finance or IT consultant.\n\n"
    "Flag ONLY these:\n"
    "- a company name with a VISIBLE STRUCTURAL DEFECT: a word cut off "
    "mid-spelling ('Disease Resea'), a missing space between words "
    "('Sign& Service'), doubled or stray punctuation. You CANNOT tell whether "
    "an unfamiliar name is real, so an unusual, short, foreign, or "
    "oddly-punctuated name is NOT a defect — real companies are called 'Good "
    "Trouble', 'Dint+', 'Artemis Aba'. Only flag damage you can SEE in the "
    "characters.\n"
    "- a job title pasted raw from a listing: a run-on stringing several roles "
    "or duties together, a stray code or ID, a duplicated word, a location or "
    "seniority tag left dangling\n"
    "- a sentence that is grammatically broken or says the same thing twice\n\n"
    "Do NOT flag ANY of the following. They are deliberate and correct:\n"
    "- all-lowercase text, missing capitalization, no greeting, no signature\n"
    "- casual or clipped phrasing, sentence fragments, informal punctuation\n"
    "- industry shorthand: 'fractional cfo', 'controller', 'fp&a', 'ciso', "
    "'vp of finance', 'devops' — these are exactly what these readers say\n"
    "- tone, persuasiveness, formatting, length, or word choice you would "
    "personally have made differently\n\n"
    "Return JSON {\"issues\": [{\"quote\": \"...\", \"why\": \"...\"}]}. The "
    "quote MUST be copied character-for-character from the email. `why` is at "
    "most 12 words.\n\n"
    "MOST EMAILS HAVE ZERO ISSUES. An empty list is the normal, expected answer. "
    "Only flag something you are confident is a genuine defect, not a "
    "preference. Never suggest replacement text."
)


# (text) -> [{"quote": ..., "why": ...}]. Injectable so tests stay offline and
# deterministic, exactly like the Gate B fit check.
NaturalnessFn = Callable[[str], list[dict[str, str]]]


def _verified(issues: list[Any], text: str) -> list[dict[str, str]]:
    """Keep only issues whose quote is really in `text`, deduped, capped.

    The verbatim test is what makes this safe to show: an operator who reads
    "this phrase sounds off" and cannot find the phrase has been sent on an
    errand by a hallucination."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for issue in issues or []:
        if not isinstance(issue, dict):
            continue
        quote = str(issue.get("quote") or "").strip()
        why = str(issue.get("why") or "").strip()
        if not quote or quote in seen or quote not in text:
            continue
        seen.add(quote)
        out.append({"quote": quote, "why": why})
        if len(out) >= _MAX_ISSUES:
            break
    return out


def check_naturalness(text: str, *, model: str = "gpt-4o-mini") -> list[dict[str, str]]:
    """Spans of `text` that read as machine-written. Never raises: an advisory
    read is not worth failing a run over, so any error yields no issues."""
    if not (text or "").strip():
        return []
    try:
        from openai import OpenAI

        from system_b import config

        config.require("OPENAI_API_KEY")
        client = OpenAI(api_key=config.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text},
            ],
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return _verified(data.get("issues") or [], text)
    except Exception:  # noqa: BLE001 — advisory only, never fails the run
        log.warning("naturalness check failed — continuing without it", exc_info=True)
        return []
