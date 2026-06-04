# Report Triage Lifecycle — Abstract Behavioral Contract

Layer A document. No Python code. No organization-specific strings.
No references to any Layer C adapter or concrete implementation.

---

## 1. Abstract Lifecycle

The report triage workflow operates as a recurring cycle. Each cycle begins
when a structured tabular report arrives from an external source. The engine
parses the report into normalized line items, compares each item against a
persistent tracker, classifies the result, groups items by responsible owner,
drafts a proposed action for each item, and then halts for human approval
before executing any action.

The cycle produces two classes of persistent output:

- **Tracker state** — a mutable record of every item currently open. Each
  item is keyed by a stable identifier derived from the report content. The
  tracker records how long an item has been open, how many times it has
  appeared, and its current classification.

- **Repository state** — an append-only archive of every item that has
  been resolved or closed. Items enter the repository when they are no
  longer present in a report cycle or when a human explicitly closes them.
  Repository rows are never updated after they are written.

---

## 2. Autonomy Gate

The engine operates in a draft-then-approve model. No action with external
side effects (sending a message, writing to an external system) may be
executed without explicit human approval for that specific item in that
specific run.

The approval scope is per-item per-run. Approval granted in a prior run does
not carry forward. The engine may draft the same action in subsequent runs if
the item remains open, but must request fresh approval each time.

Draft output is non-mutating. The engine may freely write draft artifacts
(JSON summaries, proposed message text) to internal storage without approval.
Draft artifacts must be clearly distinguishable from executed actions.

---

## 3. Agent-Immutable Field Contract

The tracker schema includes two fields that the engine reads but never
modifies:

- `human_notes` — free-text annotation written by a human operator.
- `human_status_override` — a human-set status that takes precedence over
  the engine's own classification.

The engine must never overwrite, blank, or modify these fields during a
normal run cycle. If the engine produces an updated tracker record, it must
copy the existing values of these fields from the prior record unchanged.

These fields are the primary mechanism by which human operators assert
control over individual items. Treating them as read-only at the engine
level is a hard invariant, not a convention.

---

## 4. Conflict Detection Protocol

A conflict arises when the engine's observation of the current report
contradicts a human operator's recorded intent.

The canonical conflict condition is: an item is present in the current
report (indicating it remains open) while `human_status_override` records
that the item has been closed or resolved by the operator.

When the engine detects this condition it must:

1. Set `conflict_flag = True` on the tracker item.
2. Populate `conflict_detail` with a brief machine-generated description of
   the contradiction (e.g., the override value and the date it was set).
3. Classify the item's `status` as `"conflict"` rather than any other status.
4. Include the item in the owner fanout so the responsible owner receives
   visibility.
5. Draft an action that surfaces the conflict for human review rather than
   drafting the normal follow-up action.

The engine must not resolve or dismiss the conflict autonomously. Only a
human operator clears a conflict, either by updating `human_status_override`
to align with the report or by acknowledging that the item has genuinely
reappeared.

---

## 5. Resolution-by-Absence

An item is considered resolved when it is absent from a report cycle in
which it was expected to appear. Absence is the primary resolution signal;
the engine does not require an explicit closed status from the external
source.

When an item present in the tracker is absent from the current report:

1. The engine archives the item to the repository with
   `resolution_type = "dropped_off_report"`.
2. The engine removes the item from the active tracker.
3. The `resolved_date` is set to the date of the current run cycle.
4. `total_days_open` and `total_runs_open` are computed from the tracker
   record at the time of archival.

If `human_status_override` was set before the item dropped off, the engine
sets `resolution_type = "manually_closed"` instead to reflect that the
human closure predated the absence.

Repository writes are append-only and irreversible. Once an item is
archived, it does not return to the active tracker if it reappears in a
future report. A reappearing item is treated as a new item with a new
`first_seen` date and a fresh `item_key` derivation.
