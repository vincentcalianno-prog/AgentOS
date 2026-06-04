"""Overlay resolver for the ACP negotiation engine.

Implements the most-restrictive-wins resolution algorithm (Diagram 3):

    base PlaybookEntry + List[Overlay]  →  ResolutionResult

Rules applied in overlay order:

1. Union reject_thresholds — all thresholds from base + each overlay are kept.
2. Remove accept_modifications — AcceptModification entries whose id appears
   in overlay.remove_accept_modification_ids are removed (position tightening).
3. Max-wins on numeric constraints — for each key in overlay.constraint_overrides
   that is numeric (int or float), the larger value wins (higher minimum =
   tighter position for the counterparty).  Non-numeric values replace the
   base value unconditionally.

Tightening only — loosening a position is not handled here.

The base PlaybookEntry is never mutated; the resolved_entry in the result is
an independent deep copy.  Full provenance is recorded as a list of tokens.
"""

from __future__ import annotations

import copy
from typing import List

from acp.schemas.playbook_schemas import (
    Overlay,
    PlaybookEntry,
    ResolutionResult,
)


class OverlayResolver:
    """Resolves a PlaybookEntry against an ordered sequence of Overlays.

    Overlays whose entry_id does not match the base entry's id are skipped;
    overlays with an empty entry_id are always applied (caller-filtered use
    case).

    Usage::

        resolver = OverlayResolver()
        result = resolver.resolve(base_entry, [counterparty_overlay, project_overlay])
        print(result.resolved_entry.reject_thresholds)
        print(result.provenance)
    """

    def resolve(
        self,
        base_entry: PlaybookEntry,
        overlays: List[Overlay],
    ) -> ResolutionResult:
        """Apply overlays to base_entry and return a ResolutionResult.

        Parameters
        ----------
        base_entry:
            The baseline PlaybookEntry to resolve against.  Not mutated.
        overlays:
            Overlays to apply in order.  Each is checked for entry_id
            compatibility before application.

        Returns
        -------
        ResolutionResult with a deep-copied resolved_entry and provenance list.
        """
        resolved: PlaybookEntry = copy.deepcopy(base_entry)
        provenance: list[str] = [f"baseline:{base_entry.id}"]

        for overlay in overlays:
            # Skip overlays targeted at a different entry
            if overlay.entry_id and overlay.entry_id != base_entry.id:
                continue

            overlay_tag = (
                f"overlay:{overlay.overlay_type}:{overlay.overlay_id}"
            )

            # 1. Union reject_thresholds
            for rt in overlay.add_reject_thresholds:
                resolved.reject_thresholds.append(copy.deepcopy(rt))
                provenance.append(
                    f"{overlay_tag} → add_reject_threshold:{rt.id}"
                )

            # 2. Remove accept_modifications by id
            ids_to_remove = set(overlay.remove_accept_modification_ids)
            if ids_to_remove:
                resolved.accept_modifications = [
                    m for m in resolved.accept_modifications
                    if m.id not in ids_to_remove
                ]
                for rid in overlay.remove_accept_modification_ids:
                    provenance.append(
                        f"{overlay_tag} → remove_accept_modification:{rid}"
                    )

            # 3. Constraint overrides — max-wins for numeric keys
            for key, new_val in overlay.constraint_overrides.items():
                prior_val = resolved.constraints.get(key)
                if (
                    isinstance(new_val, (int, float))
                    and isinstance(prior_val, (int, float))
                ):
                    if new_val > prior_val:
                        resolved.constraints[key] = new_val
                        provenance.append(
                            f"rule:max_wins:{key}={new_val}"
                            f" (was {prior_val}) via {overlay_tag}"
                        )
                    else:
                        # overlay is not tighter; base value stands
                        provenance.append(
                            f"rule:max_wins:{key}={prior_val}"
                            f" (overlay {new_val} not tighter) via {overlay_tag}"
                        )
                else:
                    # Non-numeric or new key: overlay replaces unconditionally
                    resolved.constraints[key] = new_val
                    provenance.append(
                        f"{overlay_tag} → override_constraint:{key}"
                    )

        return ResolutionResult(
            entry_id=base_entry.id,
            resolved_entry=resolved,
            provenance=provenance,
        )
