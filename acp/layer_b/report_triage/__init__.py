"""Layer B portable engine for the Recurring Report Triage & Follow-up workflow pattern.

This package contains the workflow-agnostic processing components:
  schemas        — TrackerItem and RepositoryItem dataclasses
  source_email   — email-attachment report source (arrival-driven, generic)
  parser         — tabular parser: CSV + SpreadsheetML XML-2003 + XLSX → raw rows
  normalizer     — column-map-driven normalizer: raw rows → canonical records
  tracker        — cross-run item tracker: diff / aging / resolution / escalation
  fanout         — group-by-owner fan-out
  executor       — ActionExecutor abstract interface
  storage_adapter — StorageAdapter abstract interface

All components in this package are Antora-free and deployment-agnostic.
Layer C config drives every deployment-specific decision (column maps,
thresholds, owner rosters, action implementations, storage backends).
"""
