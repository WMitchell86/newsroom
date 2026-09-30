"""Comparing the LIVE API shape against the declared TypeScript DTOs.

A method the previous passes never used: fetch the running server and diff
its JSON against `frontend/src/api/dto.ts`, rather than reading either side
and assuming they agree. Contracts drift silently — a field renamed on one
side keeps compiling on the other until a component dereferences it.

RESULT OF THIS SCAN, recorded so it is not redone:

  /api/v1/stories   12 runtime fields, 12 declared — exact match.
  /api/v1/stories/hint (this session's endpoint) 7 / 7, items 4 / 4 —
                    exact match.
  /api/v1/today     MISMATCH, below.

THE MISMATCH. `TodayProjection` declares `roleHealth?: RoleHealth[]`. The
live /api/v1/today response does not contain the field at all — its eight
keys are articlesRequiringAction, groupingHealth, lastRefresh,
newDevelopments, newStories, problems, scope, storyAttentionShown,
storyAttentionTotal.

Two problems, one latent:

1. The server never sends it. It is a leftover from when role health was
   part of the Today payload; it now comes from a separate endpoint
   (`getRoleHealth`, query key ["role-health"]) and is rendered by
   `TodayHeader` from that query, not from the projection.

2. The declared type is wrong even for the field that does exist.
   `TodayHeader` expects
     { ok, roles, unroutableRoles, remedy } | null
   while the DTO says `RoleHealth[]` — an array. The two are not the same
   shape, so wiring the projection field to the component would fail to
   type-check at best and render nothing at worst.

It is optional, so nothing crashes today and there is no live incident.
It is recorded because an optional field that is never sent, with a type
that contradicts its only real consumer, is exactly what the next person
wires up by mistake.
"""

import json
import urllib.error
import urllib.request

import pytest

#: The fields `TodayProjection` actually declares, read from the live response.
#:
#: `roleHealth` is NOT here, and that is the point. The scan in this module's
#: docstring found it declared-but-never-sent, and the DTO has since had it
#: removed; this set was left holding the old value, so the contract check went
#: on failing against a field no longer declared anywhere. A contract test whose
#: expected side is hand-maintained drifts exactly like the code it guards.
TODAY_DECLARED = {
    "lastRefresh", "scope", "groupingHealth", "storyAttentionTotal",
    "storyAttentionShown", "newDevelopments", "newStories", "articlesRequiringAction",
    "problems",
}


def _get(path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:8123{path}", timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))["data"]


def test_today_returns_every_field_the_projection_declares():
    """Probes the RUNNING server, so it is a probe and not a unit test.

    It skips when the workbench is not up, rather than failing: a contract
    check that reports "the server is not running" as a contract violation
    trains people to ignore it. The finding itself is in the docstring and
    does not depend on this test executing.
    """
    try:
        payload = _get("/api/v1/today")
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"workbench not reachable on 8123: {type(exc).__name__}")
    missing = TODAY_DECLARED - set(payload)
    assert not missing, f"declared in TodayProjection but never sent: {sorted(missing)}"
