"""Group-by-owner fan-out for report triage.

Accepts a list of TrackerItems and returns a dict keyed by owner with
their respective item lists. The owner field on each TrackerItem is
populated by the normalizer (using Layer C owner-fallback rules) before
this step — fanout has no fallback logic of its own.

Items with an empty or missing owner are grouped under the empty-string
key so callers can handle them explicitly rather than silently dropping them.
"""

from __future__ import annotations

from acp.layer_b.report_triage.schemas import TrackerItem


def fan_out_by_owner(items: list[TrackerItem]) -> dict[str, list[TrackerItem]]:
    """Group TrackerItems by owner.

    Args:
        items: List of TrackerItem instances. The owner field on each item
               must already be resolved (normalizer step completed).

    Returns:
        Dict mapping owner → list of TrackerItems for that owner.
        Items with an empty owner string are grouped under key "".
        Dict is ordered by insertion order (Python 3.7+ dict guarantee),
        which follows the order items appear in the input list.

    Raises:
        NotImplementedError: Implementation deferred to Phase 2.
    """
    raise NotImplementedError("fan_out_by_owner() — deferred to Phase 2.")
