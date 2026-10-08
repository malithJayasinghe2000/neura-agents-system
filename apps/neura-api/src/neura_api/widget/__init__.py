"""The embeddable widget's assets, read from disk once.

``widget.js`` is the shipped artefact **and** the source — there is no build
step (ADR-0019 §1), so what a merchant's browser executes is the file in this
directory, byte for byte. That property is worth keeping: a bundled widget would
need a check that the bundle matches its source, and this one cannot drift.

Read at import rather than per request. The file is a few kilobytes and never
changes within a process, so a disk read per shopper would be pure latency.
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).parent

WIDGET_JS = (_HERE / "widget.js").read_text(encoding="utf-8")
PAIRS_JS = (_HERE / "pairs.js").read_text(encoding="utf-8")
DEMO_HTML = (_HERE / "demo.html").read_text(encoding="utf-8")

__all__ = ["DEMO_HTML", "PAIRS_JS", "WIDGET_JS"]
