"""M2.3 blind mapping + scorecard helpers - stdlib, deterministic."""

from __future__ import annotations

import hashlib
import json
import random

SCORECARD_FIELDS = (
    "factual_correctness",
    "headline_quality",
    "opening_quality",
    "natural_bulgarian",
    "fits_style",
    "needs_editing",
)


def blind_order(group_id, draft_ids):
    rng = random.Random("m23-blind:" + group_id)
    order = list(draft_ids)
    rng.shuffle(order)
    labels = ["A", "B", "C", "D"][: len(order)]
    mapping = dict(zip(labels, order))
    fingerprint = hashlib.sha256(
        json.dumps({"group": group_id, "order": order}, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()[:12]
    return {
        "group_id": group_id,
        "labels": {label: mapping[label] for label in labels},
        "fingerprint": fingerprint,
    }


def blank_scorecard():
    return {field: None for field in SCORECARD_FIELDS} | {
        "would_publish_after_edit": None,
        "change_first": "",
    }


def validate_scorecard(scored):
    for field in SCORECARD_FIELDS:
        value = scored.get(field)
        if value is not None and (not isinstance(value, int) or not 1 <= value <= 5):
            raise ValueError(f"bad score {field}: {value!r}")
    if scored.get("would_publish_after_edit") not in (None, "YES", "NO"):
        raise ValueError("would_publish_after_edit must be YES/NO")
    return True
