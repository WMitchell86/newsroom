"""Every `source_type` the product can emit must have a Bulgarian label.

V1.2-G4.35. `SOURCE_TYPE_LABELS` is a plain dict whose caller falls back to the
raw value (`workbench/html.py`). An unlabelled type therefore does not fail — it
renders as `story_research_basis` in the «Статии» list, which is the exact shape
of the class-8 failure: a confident-looking screen stating something the system
did not verify.

Two rounds went through this file before anything noticed. `opened_publication`
was shipped in `c4e1324` with no label and was caught only by grepping for my own
new string. Three more (`story_research_basis`, `municipality_press`,
`organizer_and_ticket_platform`) were already in the operator's own
`ideas.jsonl`, rendering raw, and were found by reading the STORE rather than the
code.

The strict fix — an allow-list in `ideas.validate_idea` — needs a decision about
which types are legal, and that is an operator's, not this file's. This is the
version that needs no decision: walk every producer in `src/`, plus the values
already stored, and fail on any type with no label. That is a coverage check, not
a legality check, and it closes the gap that let all four through.
"""

import json
import re
from pathlib import Path

import pytest

from editor_assistant.workflow.workbench.labels import SOURCE_TYPE_LABELS

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "editor_assistant"

#: `source_type="literal"` and `SOURCE_TYPE = "literal"`, the two shapes the
#: codebase uses to declare a type it can produce.
PRODUCER = re.compile(r"""(?:source_type\s*=\s*|SOURCE_TYPE\s*=\s*)["']([a-z_]+)["']""")

#: A stored value, not a producer, and still something the editor can see.
STORED = ROOT / "var" / "editorial_workflow" / "ideas.jsonl"


def _produced_types() -> set[str]:
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        found.update(PRODUCER.findall(path.read_text(encoding="utf-8")))
    return found


def _stored_types() -> set[str]:
    if not STORED.exists():
        return set()
    values: set[str] = set()
    for line in STORED.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line).get("source_type")
        except (ValueError, AttributeError):
            continue
        if value:
            values.add(str(value))
    return values


def test_every_type_the_code_can_produce_has_a_label():
    missing = sorted(name for name in _produced_types() if name not in SOURCE_TYPE_LABELS)
    assert not missing, (
        f"these source_type values are produced in src/ but render raw in the "
        f"editor: {missing}"
    )


def test_every_stored_type_has_a_label():
    stored = _stored_types()
    if not stored:
        pytest.skip(f"no operator store at {STORED}")
    missing = sorted(name for name in stored if name not in SOURCE_TYPE_LABELS)
    assert not missing, (
        f"these source_type values are in the operator's store and render raw: {missing}"
    )


def test_the_scan_actually_finds_producers():
    """A scan that matches nothing would pass every test above vacuously.

    Written after the same class of mistake twice: a lazy capture, and a lazy
    patch. This asserts the detector works before trusting what it says.
    """
    produced = _produced_types()
    assert len(produced) >= 4, f"the producer scan found almost nothing: {sorted(produced)}"
    assert "story_research_basis" in produced
    assert "chernomorie_archive" in produced
