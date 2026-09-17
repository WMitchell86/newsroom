"""M2.7 IdeaCard contract - lightweight editor-facing idea cards.

Stdlib only. `possible_angle` is an AI suggestion, never source truth: it is
always stored with an explicit [SUGGESTION] prefix. No drafting is
auto-triggered by an idea card; status transitions are explicit.
"""

from __future__ import annotations

import json
from pathlib import Path

IDEA_STATUSES = ("NEW", "DRAFT_REQUESTED", "IGNORED", "FOLLOW_UP", "NO_PUBLISHABLE_ANGLE")
REQUIRED_TOP = (
    "idea_id",
    "created_at",
    "source_type",
    "source_url",
    "source_reference",
    "title",
    "what_changed",
    "why_now",
    "location",
    "possible_angle",
    "status",
)
ANGLE_PREFIX = "[SUGGESTION]"


class IdeaError(ValueError):
    pass


def validate_idea(idea):
    if not isinstance(idea, dict):
        raise IdeaError("idea must be a dict")
    for key in REQUIRED_TOP:
        if key not in idea:
            raise IdeaError(f"idea missing key: {key}")
    if not idea["idea_id"] or not idea["title"] or not idea["what_changed"]:
        raise IdeaError("idea_id, title and what_changed must be non-empty")
    if idea["status"] not in IDEA_STATUSES:
        raise IdeaError(f"bad idea status: {idea['status']!r}")
    angle = idea["possible_angle"]
    if angle and not angle.startswith(ANGLE_PREFIX):
        raise IdeaError("possible_angle must be an explicit [SUGGESTION], never source truth")
    return True


def make_idea(
    *,
    idea_id,
    created_at,
    source_type,
    source_url,
    source_reference,
    title,
    what_changed,
    why_now="",
    location="",
    possible_angle="",
    status="NEW",
):
    if possible_angle and not possible_angle.startswith(ANGLE_PREFIX):
        possible_angle = f"{ANGLE_PREFIX} {possible_angle}"
    idea = {
        "idea_id": idea_id,
        "created_at": created_at,
        "source_type": source_type,
        "source_url": source_url,
        "source_reference": source_reference,
        "title": title,
        "what_changed": what_changed,
        "why_now": why_now,
        "location": location,
        "possible_angle": possible_angle,
        "status": status,
    }
    validate_idea(idea)
    return idea


def request_draft(idea):
    """Explicit editor action: mark the idea as ready for drafting."""
    if idea["status"] not in ("NEW", "FOLLOW_UP"):
        raise IdeaError(f"cannot request draft from status {idea['status']!r}")
    idea["status"] = "DRAFT_REQUESTED"
    return idea


def save_ideas(ideas, path):
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for idea in ideas:
            validate_idea(idea)
            fh.write(json.dumps(idea, ensure_ascii=False, sort_keys=True) + "\n")
    return out


def read_ideas(path):
    ideas = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                idea = json.loads(line)
                validate_idea(idea)
                ideas.append(idea)
    return ideas
