"""Synthetic LRS renderer fixture for Agent 7 (LRS Generator) tests.

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparties: Acme Industrial, Beta Manufacturing, Gamma Components
    Tenant owners: alice, bob, carol

Provides deterministic RenderLRSFn stubs:
  - make_fixed_renderer()     — returns the same output for every LRSInput
  - make_markdown_renderer()  — builds a structured markdown summary from the
                                three input dicts; generic, no contract-type logic
  - ACME_INDUSTRIAL_RENDERER  — make_markdown_renderer() instance for the Acme
                                Industrial round-1 scenario
"""

from __future__ import annotations

from acp.layer_b.agents.lrs_generator import LRSInput, LRSOutput, RenderLRSFn


def make_fixed_renderer(
    document_bytes: bytes = b"SYNTHETIC LRS DOCUMENT",
    document_format: str = "txt",
    metadata: dict | None = None,
) -> RenderLRSFn:
    """Return a RenderLRSFn that returns the same output for every LRSInput."""
    _metadata = metadata if metadata is not None else {}

    def _render(lrs_input: LRSInput) -> LRSOutput:
        return LRSOutput(
            document_bytes=document_bytes,
            document_format=document_format,
            metadata=_metadata,
        )

    return _render


def make_markdown_renderer() -> RenderLRSFn:
    """Return a RenderLRSFn that produces a structured markdown summary.

    Renders the three input dicts (diff, analysis, counter_proposals) as
    section headers with clause-level bullet points. No assumptions about
    contract type, structure, or domain terminology — proves orchestration
    only. Real contract-type-specific renderers live in layer_c_antora.
    """
    def _render(lrs_input: LRSInput) -> LRSOutput:
        lines: list[str] = [
            "# Legal Review Summary",
            "",
            "## Negotiation Details",
            f"- Negotiation ID: {lrs_input.negotiation_id}",
            f"- Workflow: {lrs_input.workflow_id}",
            f"- Contract Type: {lrs_input.contract_type}",
            f"- Counterparty: {lrs_input.counterparty_name}",
            f"- Round: {lrs_input.round_number}",
            "",
        ]

        # Diff section
        lines.append("## Structural Diff")
        diff_entries = lrs_input.diff.get("entries", [])
        if diff_entries:
            for entry in diff_entries:
                ref = entry.get("clause_reference", "?")
                change = entry.get("change_type", "?")
                lines.append(f"- Clause {ref}: {change}")
        else:
            lines.append("- No diff entries.")
        lines.append("")

        # Analysis section
        lines.append("## Redline Analysis")
        recommendations = lrs_input.analysis.get("recommendations", [])
        if recommendations:
            for rec in recommendations:
                ref = rec.get("clause_reference", "?")
                recommendation = rec.get("recommendation", "?")
                lines.append(f"- Clause {ref}: {recommendation}")
        else:
            lines.append("- No analysis recommendations.")
        lines.append("")

        # Counter-proposals section
        lines.append("## Counter-Proposals")
        drafts = lrs_input.counter_proposals.get("drafts", [])
        if drafts:
            for draft in drafts:
                ref = draft.get("clause_reference", "?")
                tone = draft.get("tone", "?")
                lines.append(f"- Clause {ref} ({tone}): {draft.get('counter_text', '')}")
        else:
            lines.append("- No counter-proposals.")
        lines.append("")

        document = "\n".join(lines)
        return LRSOutput(
            document_bytes=document.encode(),
            document_format="md",
            metadata={
                "section_count": 3,
                "diff_entry_count": len(diff_entries),
                "recommendation_count": len(recommendations),
                "draft_count": len(drafts),
            },
        )

    return _render


ACME_INDUSTRIAL_RENDERER: RenderLRSFn = make_markdown_renderer()
