"""Tidy lead names with a model, behind a code guard (2026-10-25).

Organization names arrive as their registry spelled them: "Vip Structures",
"Foundation For University Hospital A New Jersey Nonprofit Co", "Refugee
Support Services Of Thecarolinas", "Solid Ground Gen CNTRCTNG". The rules in
`clients.inventory._clean_company_name` catch the regular patterns; the first
200-email batch still had ~20 such names in ~40 emails. The user chose to let
a model fix them, and to have the finished review gate checked as the safety
net.

The model may change HOW a name is written, never WHICH name it is. Code keeps
a fix only when `same_name` holds:

  * the same letters in the same order, ignoring case, spaces and punctuation
    ("Thecarolinas" -> "The Carolinas", "N B C-U S A" -> "NBC-USA"); or
  * the original's words, in order, where each kept word is unchanged or
    spelled out from its abbreviation ("Gen CNTRCTNG" -> "General
    Contracting": same first letter, the short form's letters inside the long
    one), dropping only filler words, a trailing legal tail ("A New Jersey
    Nonprofit Co", "Limited Liability Company") or a single cut-off letter.

A fix that fails the guard is not applied; the name stays as the registry wrote
it and the review card says so. Every applied fix is listed on its card too, so
the end-of-batch review can see exactly what the model changed.

Fixes are cached by the original name (`data/name-fixes.json`, gitignored), so
a lead given to fifteen firms costs one call, and tomorrow's run reuses today's
answers.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable, Iterable

log = logging.getLogger("system_b.names")

DEFAULT_CACHE = Path(__file__).resolve().parent.parent / "data" / "name-fixes.json"
MODEL = "gpt-4o"
# Bumped when the instructions change: names the old prompt left unchanged are
# asked again (fixes it made are kept).
PROMPT_VERSION = 2
_CHUNK = 40

# Words a name may lose without becoming another name.
_FILLER = frozenset({"the", "a", "an", "of", "and", "inc", "incorporated", "llc", "l",
                     "c", "co", "corp", "corporation", "company", "ltd", "limited",
                     "pllc", "pc", "org", "llp", "lp", "pa", "plc"})
# A trailing run of words is a legal tail when it holds one of these.
_LEGAL = frozenset({"inc", "incorporated", "llc", "co", "corp", "corporation", "company",
                    "ltd", "limited", "liability", "nonprofit", "org", "pllc", "pc",
                    "llp", "lp", "pa", "plc"})

_SYSTEM = (
    "You tidy organization names for a cold email. Each name is a real "
    "organization's registered name, often in the registry's odd casing or "
    "with legal filler.\n\n"
    "For each name return how a person would write it in an email:\n"
    "- fix capitalization: acronyms in capitals ('Vip Structures' -> 'VIP "
    "Structures', 'Kla Roofing' -> 'KLA Roofing'), normal words in title case. "
    "A 2-4 letter word that is not an English word or a common first name is "
    "almost always initials: 'Rac Construction' -> 'RAC Construction', 'Gwo, "
    "Inc.' -> 'GWO'\n"
    "- fix spacing: split words run together ('Thecarolinas' -> 'The "
    "Carolinas'), join spaced-out initials ('N B C-U S A' -> 'NBC-USA')\n"
    "- spell out registry abbreviations ('Gen CNTRCTNG' -> 'General "
    "Contracting') and abbreviated US states ('For Tex' -> 'for Texas')\n"
    "- finish a last word the registry cut off when the completion is "
    "obvious ('Neighborhood Center Pro' -> 'Neighborhood Center Program')\n"
    "- drop legal filler at the end ('A New Jersey Nonprofit Co', 'Limited "
    "Liability Company', 'Inc', 'LLC') and a single cut-off letter at the end\n"
    "- move a trailing ', The' to the front\n\n"
    "NEVER add a word that is not in the name or an abbreviation of a word in "
    "it, never reorder words, never translate, never guess a different "
    "organization. If a name already reads fine, return it unchanged.\n\n"
    'Return JSON {"names": [{"in": "<exactly as given>", "out": "<tidied>"}]}.'
)

# (names) -> {original: tidied}. Injectable so tests stay offline.
FixFn = Callable[[list[str]], dict[str, str]]


_TRAILING_THE_RE = re.compile(r"[,.]\s*the\s*$", re.IGNORECASE)


def front_the(name: str) -> str:
    """Registries file "San Francisco Housing Accelerator Fund, The"; an email
    says "The San Francisco Housing Accelerator Fund"."""
    m = _TRAILING_THE_RE.search(name or "")
    return f"The {name[:m.start()].strip()}" if m and name[:m.start()].strip() else name


def _words(name: str) -> list[str]:
    # An apostrophe joins: "Children's" is the word "childrens", not "children" + "s".
    return re.findall(r"[a-z0-9]+", re.sub(r"['\u2019]", "", (name or "").lower()))


def _subseq(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def _spelled_out(orig: str, fixed: str) -> bool:
    return orig == fixed or (len(orig) >= 2 and orig[0] == fixed[0]
                             and len(fixed) > len(orig) and _subseq(orig, fixed))


def same_name(original: str, fixed: str) -> bool:
    """True when `fixed` is `original` written better, not another name."""
    if not fixed or not fixed.strip():
        return False
    # A legal form may be dropped, never invented ("Inc" -> "LLC").
    if {w for w in _words(fixed) if w in _LEGAL} - set(_words(original)):
        return False
    # The same letters, once legal forms are set aside: "12Angels Construction
    # LLC" -> "12 Angels Construction", "Of Thecarolinas Inc" -> "of the Carolinas".
    def letters(name: str) -> str:
        return "".join(w for w in _words(name) if w not in _LEGAL)
    if letters(original) == letters(fixed):
        return True
    # "The" keeps its place: a trailing ", The" may move to the front, and
    # nothing else may move it ("The X Fund" -> "X Fund, The" is refused).
    orig, new = _words(original), _words(fixed)
    if len(orig) > 1 and orig[-1] == "the":
        orig = ["the"] + orig[:-1]
    i = 0
    for w in new:
        while i < len(orig) and not _spelled_out(orig[i], w):
            if orig[i] not in _FILLER:
                return False           # skipped a real word
            i += 1
        if i == len(orig):
            return False               # a word the original never had
        i += 1
    tail = orig[i:]
    return (not tail or all(w in _FILLER for w in tail)
            or any(w in _LEGAL for w in tail) or (len(tail) == 1 and len(tail[0]) == 1))


def openai_fix(names: list[str]) -> dict[str, str]:
    """One model call for a chunk of names. Raises on failure (the caller
    keeps the originals)."""
    from openai import OpenAI

    from system_b import config

    config.require("OPENAI_API_KEY")
    client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=60)
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _SYSTEM},
                  {"role": "user", "content": json.dumps({"names": names})}],
    )
    data = json.loads(resp.choices[0].message.content or "{}")
    return {str(r.get("in")): str(r.get("out") or "") for r in data.get("names") or []
            if isinstance(r, dict)}


class NameFixer:
    """Original name -> the name to print, with a record of what changed."""

    def __init__(self, fix: FixFn | None = openai_fix, cache_path: Path | None = DEFAULT_CACHE):
        self._fix = fix
        self._path = cache_path
        self._cache: dict[str, dict[str, str]] = {}
        if cache_path and cache_path.exists():
            try:
                self._cache = json.loads(cache_path.read_text())
            except (OSError, ValueError):
                log.warning("name cache unreadable — starting empty")
        # Every answer is judged again by this guard: a refusal it now
        # accepts is applied, a fix it now refuses is undone.
        for name, entry in self._cache.items():
            if entry.get("status") == "rejected" and same_name(name, entry.get("proposed", "")):
                self._cache[name] = {"out": entry["proposed"], "status": "fixed"}
            elif entry.get("status") == "fixed" and not same_name(name, entry.get("out", "")):
                self._cache[name] = {"out": name, "status": "rejected",
                                     "proposed": entry.get("out", "")}
        # tidied name -> the registry's, so a lead already renamed for one firm
        # still carries its note on the next firm's card.
        self._origin = {e["out"]: n for n, e in self._cache.items() if e.get("status") == "fixed"}

    def prime(self, names: Iterable[str]) -> None:
        """Ask the model about every name not yet cached, in chunks."""
        def stale(n: str) -> bool:
            e = self._cache.get(n)
            return e is None or (e.get("status") == "unchanged"
                                 and e.get("v", 1) < PROMPT_VERSION)
        todo = list(dict.fromkeys(n for n in names if n and stale(n)))
        if not todo or self._fix is None:
            return
        for start in range(0, len(todo), _CHUNK):
            chunk = todo[start:start + _CHUNK]
            try:
                answers = self._fix(chunk)
            except Exception:  # noqa: BLE001 — a failed call keeps the originals
                log.warning("name fixer failed — keeping %d names as written", len(chunk),
                            exc_info=True)
                continue
            for name in chunk:
                out = (answers.get(name) or "").strip()
                if not out or out == name:
                    self._cache[name] = {"out": name, "status": "unchanged",
                                         "v": PROMPT_VERSION}
                elif same_name(name, out):
                    self._cache[name] = {"out": out, "status": "fixed"}
                    self._cache.setdefault(out, {"out": out, "status": "unchanged",
                                                 "v": PROMPT_VERSION})
                    self._origin[out] = name
                else:
                    self._cache[name] = {"out": name, "status": "rejected", "proposed": out}
        self.save()

    def tidy(self, leads: Iterable) -> list[str]:
        """Rename these leads in place (one model call for any not cached) and
        return the review-card notes for them."""
        live = [ld for ld in leads if ld is not None and getattr(ld, "company", None)]
        self.prime(self._origin.get(ld.company, ld.company) for ld in live)
        notes: list[str] = []
        for ld in live:
            original = self._origin.get(ld.company, ld.company)
            ld.company = front_the((self._cache.get(original) or {}).get("out") or original)
            note = self.note(original)
            if note and note not in notes:
                notes.append(note)
        return notes

    def __call__(self, name: str) -> str:
        self.prime([name])
        return front_the((self._cache.get(name) or {}).get("out") or name)

    def note(self, name: str) -> str | None:
        """The review-card line for a name the fixer touched, or None."""
        from system_b.copy.email import spoken_name

        entry = self._cache.get(name) or {}
        # Dropping "Inc" or "LLC" changes nothing an email prints (`spoken_name`
        # drops them already), so it is not worth a line on the card.
        if entry.get("status") == "fixed" and spoken_name(name) == spoken_name(entry["out"]):
            return None
        if entry.get("status") == "fixed":
            return f"name tidied by the model: \"{name}\" -> \"{entry['out']}\""
        if entry.get("status") == "rejected":
            return (f"name kept as the registry wrote it (\"{name}\"); the model "
                    f"proposed \"{entry['proposed']}\", which is not the same name")
        return None

    def save(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._cache, indent=1, sort_keys=True))
        except OSError:
            log.warning("could not write the name cache", exc_info=True)
