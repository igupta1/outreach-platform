"""Answers the model already gave, kept between runs (2026-11-13, the user:
"reduce our api usage without sacrificing quality").

The claim check ("does this phrase say the firm serves construction?") and
the fit check ("is this lead a construction company?") run at temperature 0
on the same inputs night after night: a batch that is not downloaded comes
back the next night, and the same leads are judged for many firms. The same
question gets the same answer, so it is asked once.

One JSON file, `data/model-cache.json` (prospect-free, but under data/, so
never committed). It is written in place, not renamed over, because the
nightly checkout reaches it through a symlink. Any read or write failure
just means asking the model again.
"""

from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "model-cache.json"
_mem: dict[str, bool] | None = None
_dirty = 0


def _load() -> dict[str, bool]:
    global _mem
    if _mem is None:
        try:
            _mem = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {}
        except (OSError, ValueError):
            _mem = {}
    return _mem


def get(kind: str, *parts: str) -> bool | None:
    return _load().get("|".join((kind, *parts)))


def put(kind: str, *parts: str, value: bool) -> None:
    global _dirty
    _load()["|".join((kind, *parts))] = bool(value)
    _dirty += 1
    if _dirty >= 20:
        flush()


def flush() -> None:
    global _dirty
    if _mem is None or not _dirty:
        return
    try:
        with PATH.open("w", encoding="utf-8") as fh:      # in place: may be a symlink
            json.dump(_mem, fh)
        _dirty = 0
    except OSError:
        pass
