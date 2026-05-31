"""Mock redline generator for the ACP dry-run harness.

Reads inputs/sample_mepa_base.md and applies configurable modification patterns
to produce a synthetic counterparty-redlined version. The output simulates the
kind of redlined document a counterparty would send back via email.

Modification patterns:
    "payment_terms"           — 2.9: add extra liability language (accepted_with_addition)
    "payment_delay"           — 3.2: extend payment terms from net-30 to net-45 (modified)
    "termination_notice"      — 4.4: shorten termination notice from 60 to 30 days (modified)
    "indemnity_deletion"      — 6.1: delete mutual indemnification clause (deleted)
    "force_majeure_expansion" — 7.2: expand force majeure definition (modified)

Each pattern is independent. Combine any subset.

Usage:
    from mock_redline_generator import generate_redline

    redline_md = generate_redline(patterns=["payment_delay", "indemnity_deletion"])

Or from the CLI:
    python3 mock_redline_generator.py --patterns payment_delay indemnity_deletion \
        --out /tmp/redlined_mepa.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BASE_PATH = Path(__file__).parent / "inputs" / "sample_mepa_base.md"

# ---------------------------------------------------------------------------
# Modification functions — each takes the full document dict and modifies
# the relevant clause in-place.
# ---------------------------------------------------------------------------

_ORIGINAL_CLAUSES: dict[str, str] = {
    "2.9": (
        "Each party's aggregate liability under this Agreement shall be limited to direct damages only. "
        "In no event shall either party be liable for indirect, incidental, consequential, punitive, or "
        "exemplary damages, regardless of whether such damages are based on contract, tort, strict liability, "
        "or any other theory."
    ),
    "3.2": (
        "Counterparty shall pay all invoices within thirty (30) days of the invoice date. Invoices not paid "
        "within such period shall accrue interest at the lesser of (a) one and one-half percent (1.5%) per "
        "month or (b) the maximum rate permitted by applicable law."
    ),
    "4.4": (
        "Either party may terminate this Agreement for any reason upon sixty (60) days prior written notice "
        "to the other party, provided that all Transaction Confirmations in effect shall continue to be "
        "performed for their stated terms unless separately terminated."
    ),
    "5.1": (
        "Each party represents and warrants that: (a) it is duly organized and validly existing; "
        "(b) it has full authority to execute and perform this Agreement; "
        "(c) execution does not violate any law, regulation, or agreement to which it is a party."
    ),
    "6.1": (
        "Each party (the \"Indemnifying Party\") shall indemnify, defend, and hold harmless the other party "
        "and its officers, directors, employees, and agents from and against any and all third-party claims, "
        "losses, damages, liabilities, costs, and expenses (including reasonable attorneys' fees) arising "
        "out of or related to the Indemnifying Party's breach of this Agreement or gross negligence or "
        "willful misconduct."
    ),
    "7.2": (
        "\"Force Majeure Event\" means any event beyond the reasonable control of the affected party, "
        "including but not limited to: acts of God, fire, flood, earthquake, storm, lightning, epidemic, "
        "war, terrorism, acts of governmental authority, grid operator curtailment orders, or failure of "
        "third-party transmission facilities."
    ),
    "8.3": (
        "Any legal proceeding arising under this Agreement shall be brought exclusively "
        "in the state or federal courts located in Travis County, Texas."
    ),
}

_COUNTERPARTY_MODIFICATIONS: dict[str, dict] = {
    "payment_terms": {
        "clause": "2.9",
        "heading": "### 2.9 Liability Cap",
        "description": "accepted_with_addition: counterparty accepted base cap but added carve-out for gross negligence",
        "new_text": (
            "Each party's aggregate liability under this Agreement shall be limited to direct damages only. "
            "In no event shall either party be liable for indirect, incidental, consequential, punitive, or "
            "exemplary damages, regardless of whether such damages are based on contract, tort, strict liability, "
            "or any other theory. "
            "Notwithstanding the foregoing, the limitation on consequential damages shall not apply in cases "
            "of gross negligence, willful misconduct, or fraud by either party."
        ),
    },
    "payment_delay": {
        "clause": "3.2",
        "heading": "### 3.2 Payment Terms",
        "description": "modified: counterparty proposes net-45 instead of net-30",
        "new_text": (
            "Counterparty shall pay all invoices within forty-five (45) days of the invoice date. Invoices not "
            "paid within such period shall accrue interest at the lesser of (a) one percent (1.0%) per month "
            "or (b) the maximum rate permitted by applicable law."
        ),
    },
    "termination_notice": {
        "clause": "4.4",
        "heading": "### 4.4 Termination for Convenience",
        "description": "modified: counterparty proposes 30-day notice instead of 60-day",
        "new_text": (
            "Either party may terminate this Agreement for any reason upon thirty (30) days prior written "
            "notice to the other party, provided that all Transaction Confirmations in effect shall continue "
            "to be performed for their stated terms unless separately terminated."
        ),
    },
    "indemnity_deletion": {
        "clause": "6.1",
        "heading": "### 6.1 Mutual Indemnification",
        "description": "deleted: counterparty proposes removal of mutual indemnification clause",
        "new_text": None,  # None = delete the clause
    },
    "force_majeure_expansion": {
        "clause": "7.2",
        "heading": "### 7.2 Definition of Force Majeure",
        "description": "modified: counterparty expands force majeure to include supply chain disruptions",
        "new_text": (
            "\"Force Majeure Event\" means any event beyond the reasonable control of the affected party, "
            "including but not limited to: acts of God, fire, flood, earthquake, storm, lightning, epidemic, "
            "war, terrorism, acts of governmental authority, grid operator curtailment orders, failure of "
            "third-party transmission facilities, supply chain disruptions affecting energy components or "
            "fuel supply, or any other event that makes performance commercially impractical."
        ),
    },
    # --- Pilot-entry patterns (clause references map to authored PlaybookEntries) ---
    # Content mismatch with base MEPA is intentional: these patterns exercise
    # playbook lookup and confidence tier rendering, not template fidelity.
    "warranty_period_shortening": {
        "clause": "5.1",
        "heading": "### 5.1 Mutual Representations",
        "description": "modified: counterparty proposes 12-month warranty period instead of 36 months",
        "new_text": (
            "Each party represents and warrants that: (a) it is duly organized and validly existing; "
            "(b) it has full authority to execute and perform this Agreement; "
            "(c) execution does not violate any law, regulation, or agreement to which it is a party. "
            "Supplier's warranty obligations shall expire twelve (12) months from the date of shipment."
        ),
    },
    "lol_direct_damages_expansion": {
        "clause": "8.3",
        "heading": "### 8.3 Venue",
        "description": (
            "modified: counterparty expands direct damages to include production loss and throughput"
        ),
        "new_text": (
            "Any legal proceeding arising under this Agreement shall be brought exclusively "
            "in the state or federal courts located in Travis County, Texas. "
            "For purposes of this Agreement, direct damages shall include without limitation "
            "production interruption losses, loss of throughput, scrap costs, and rework costs "
            "arising from the other party's breach."
        ),
    },
}

_ALL_PATTERNS = list(_COUNTERPARTY_MODIFICATIONS.keys())


def generate_redline(
    patterns: list[str] | None = None,
    base_path: Path = _BASE_PATH,
) -> str:
    """Apply the given modification patterns to the base MEPA document.

    Args:
        patterns: List of pattern names to apply. Defaults to all patterns.
        base_path: Path to the base Markdown document.

    Returns:
        Modified document as a Markdown string.
    """
    if patterns is None:
        patterns = _ALL_PATTERNS

    unknown = set(patterns) - set(_COUNTERPARTY_MODIFICATIONS)
    if unknown:
        raise ValueError(f"Unknown patterns: {unknown}. Valid patterns: {_ALL_PATTERNS}")

    text = base_path.read_text()

    # Add redline header
    header_note = (
        "<!-- COUNTERPARTY REDLINE — DRY-RUN SYNTHETIC DOCUMENT -->\n"
        f"<!-- Applied modifications: {', '.join(patterns)} -->\n\n"
    )
    text = header_note + text

    # Apply each modification
    for pattern_name in patterns:
        mod = _COUNTERPARTY_MODIFICATIONS[pattern_name]
        heading = mod["heading"]
        clause = mod["clause"]
        original_text = _ORIGINAL_CLAUSES[clause]
        new_text = mod["new_text"]
        description = mod["description"]

        if new_text is None:
            # Deletion: replace the entire clause section with a strikethrough note
            clause_header = f"{heading}\n{original_text}"
            deletion_marker = (
                f"{heading}\n"
                f"~~{original_text}~~\n\n"
                f"> **[COUNTERPARTY REDLINE — DELETION PROPOSED: {description}]**"
            )
            text = text.replace(clause_header, deletion_marker)
        else:
            # Replacement or addition: swap the original text for the new text
            modification_marker = (
                f"\n\n> **[COUNTERPARTY REDLINE — {description.upper()}]**"
            )
            text = text.replace(original_text, new_text + modification_marker)

    return text


def list_patterns() -> None:
    print("Available modification patterns:")
    for name, mod in _COUNTERPARTY_MODIFICATIONS.items():
        print(f"  {name:30s} — {mod['description']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic counterparty-redlined MEPA for ACP dry-run testing."
    )
    parser.add_argument(
        "--patterns",
        nargs="+",
        choices=_ALL_PATTERNS,
        default=_ALL_PATTERNS,
        help="Modification patterns to apply (default: all).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output file path. Defaults to stdout.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available patterns and exit.",
    )
    args = parser.parse_args()

    if args.list:
        list_patterns()
        sys.exit(0)

    result = generate_redline(patterns=args.patterns)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(result)
        print(f"Redlined document written to: {args.out}")
    else:
        print(result)


if __name__ == "__main__":
    main()
