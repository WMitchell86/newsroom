"""V1.1-F2A: Story-grouping operational health.

F1 proved the dominant cause of Story fragmentation was
`B. SEMANTIC_BUDGET_EXHAUSTION`: the `story` role spent its internal daily
budget mid-corpus, and `on_exhausted = "conservative"` correctly kept the
remaining publications separate. That safety behaviour is **unchanged** by this
module.

What was missing was **visibility**. A day in which a third of the corpus is
grouped conservatively looked exactly like a day in which nothing interesting
happened, and the problem was only discovered later as duplicate Stories.

This module derives one narrow, persisted status for Story grouping:

```text
healthy | degraded | budget_exhausted | unavailable
```

It is a **derived operational signal**, not editorial state and not a new
source of truth. It never influences a merge decision, and it is deliberately
separate from source-collection health: "the feeds are down" and "grouping
could not classify" are different problems for the operator.
"""

from __future__ import annotations

from editor_assistant.workflow import story_relation

#: The four grouping states. Enum names follow the brief; the values are the
#: canonical wire values persisted in the run summary.
GROUPING_HEALTHY = "healthy"
GROUPING_DEGRADED = "degraded"
GROUPING_BUDGET_EXHAUSTED = "budget_exhausted"
GROUPING_UNAVAILABLE = "unavailable"

GROUPING_STATUSES = (
    GROUPING_HEALTHY,
    GROUPING_DEGRADED,
    GROUPING_BUDGET_EXHAUSTED,
    GROUPING_UNAVAILABLE,
)

#: Summary keys. A run that predates V1.1-F2A simply has no `grouping` key, and
#: readers must treat that as "unknown", never as "healthy".
FIELD_STATUS = "status"
FIELD_LAST_SUCCESS = "lastSuccessfulSemanticClassificationAt"
FIELD_REQUIRED = "semanticRequired"
FIELD_ANSWERED = "semanticAnswered"
FIELD_DEGRADED = "semanticDegraded"
FIELD_DEGRADED_BUDGET = "semanticDegradedBudgetExhausted"
FIELD_DEGRADED_UNAVAILABLE = "semanticDegradedUnavailable"


class GroupingHealth:
    """Accumulates one grouping run's semantic outcome and derives its status.

    The counters deliberately exclude decisions that never needed a model:
    exact publication matches, deterministic `SAME_STORY`, and plain
    `NEW_STORY`. `itemsGroupedWhileSemanticDegraded` is therefore a measure of
    **quality loss**, not of traffic — a run that grouped 200 items perfectly
    reports 0, and a run of 1 item that needed a model and did not get one
    reports 1.
    """

    def __init__(self, *, enabled: bool = True):
        self.enabled = bool(enabled)
        # Private counters: the public verbs below are methods, and a same-named
        # attribute would shadow them.
        self._required = 0
        self._answered = 0
        self._degraded = 0
        self._degraded_budget = 0
        self._degraded_unavailable = 0
        self.last_success_at: str | None = None

    def required_semantic(self) -> None:
        """A publication reached the anchored shortlist and needs a decision."""
        self._required += 1

    def answered(self, *, at: str | None = None) -> None:
        """A semantic classification returned a usable relation."""
        self._answered += 1
        if at:
            self.last_success_at = str(at)

    def failed(self, reason: str) -> None:
        """A needed classification did not happen; the item stays separate.

        This is the metric F1 said was missing. It is recorded here and used
        only for reporting: the conservative fallback itself is unchanged.
        """
        self._degraded += 1
        if reason == story_relation.FAILURE_BUDGET:
            self._degraded_budget += 1
        else:
            self._degraded_unavailable += 1

    def failure_reporter(self):
        """A callback for `story_relation.classify(on_failure=...)`."""
        if not self.enabled:
            return None

        def report(reason, _trace=None):
            self.failed(reason)

        return report

    def status(self) -> str:
        """The single derived state.

        A run that never needed the model is **healthy**: reporting
        `unavailable` because nothing asked would train the operator to ignore
        the signal, which is the opposite of what this slice is for.
        """
        if not self.enabled or not self._required:
            return GROUPING_HEALTHY
        if not self._degraded:
            return GROUPING_HEALTHY
        # A self-imposed internal limit and an external provider failure need
        # different operator responses, so the specific cause is preserved.
        if self._degraded_budget and not self._degraded_unavailable:
            return GROUPING_BUDGET_EXHAUSTED
        if self._degraded_unavailable and not self._degraded_budget:
            return GROUPING_UNAVAILABLE
        return GROUPING_DEGRADED

    def summary(self, *, at: str | None = None) -> dict:
        """The persisted, editor-safe run summary."""
        return {
            FIELD_STATUS: self.status(),
            FIELD_LAST_SUCCESS: self.last_success_at,
            FIELD_REQUIRED: self._required,
            FIELD_ANSWERED: self._answered,
            FIELD_DEGRADED: self._degraded,
            FIELD_DEGRADED_BUDGET: self._degraded_budget,
            FIELD_DEGRADED_UNAVAILABLE: self._degraded_unavailable,
        }


def read_grouping_health(record) -> dict | None:
    """The grouping block of a run summary, or `None` when absent/unreadable.

    `None` means **unknown** (a run older than this slice). Callers must not
    render a warning for an unknown state: inventing a warning for historical
    runs would be a claim the data does not support.
    """
    if not isinstance(record, dict):
        return None
    block = record.get("grouping")
    if not isinstance(block, dict):
        return None
    status = str(block.get(FIELD_STATUS) or "")
    if status not in GROUPING_STATUSES:
        return None
    return {
        FIELD_STATUS: status,
        FIELD_LAST_SUCCESS: block.get(FIELD_LAST_SUCCESS) or None,
        FIELD_REQUIRED: int(block.get(FIELD_REQUIRED) or 0),
        FIELD_ANSWERED: int(block.get(FIELD_ANSWERED) or 0),
        FIELD_DEGRADED: int(block.get(FIELD_DEGRADED) or 0),
        FIELD_DEGRADED_BUDGET: int(block.get(FIELD_DEGRADED_BUDGET) or 0),
        FIELD_DEGRADED_UNAVAILABLE: int(block.get(FIELD_DEGRADED_UNAVAILABLE) or 0),
    }


def is_healthy(record) -> bool:
    """Whether Today may stay quiet.

    Unknown and healthy both mean "no warning", for the reason documented on
    `read_grouping_health`.
    """
    block = read_grouping_health(record)
    return block is None or block[FIELD_STATUS] == GROUPING_HEALTHY
