"""Sequence layer — the pure 3-email generator.

`generate.py::generate_sequence` runs the whole pipeline for one prospect and
returns the sequence as a plain dict. No sender, no store — the CLI (`run.py`)
reads an Apollo CSV in and writes a review CSV out.
"""

from __future__ import annotations

from system_b.sequence.generate import generate_sequence

__all__ = ["generate_sequence"]
