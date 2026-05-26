"""Static discipline check for the ACP repository.

Enforces Section 13.7 (Implementation Discipline) from the Architecture Spec:
- Layer B must not import from layer_c_antora
- Layer B must not contain Antora-specific strings (supplier names, channel IDs, etc.)
- Test fixtures must not use real Antora content

Exit code 0 = clean, 1 = violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LAYER_B = ROOT / "layer_b"

# Strings that should NEVER appear in layer_b
ANTORA_FORBIDDEN = [
    # Specific people
    "Vincent Calianno",
    "Sandelin Sikes",
    "Ranjeet Mankikar",
    "Tom Butler",
    "Emily Wang",
    "Mugdha Thakkar",
    # Specific Antora suppliers from Vincent's tracker
    "Texas Transformers",
    "MCM Engineering",
    "Federal Pacific",
    "Nanez",
    "JL Precision",
    "Bizlink",
    "nVent",
    "Shermco",
    "Cummins",
    "Hitachi",
    "Toshiba",
    "Virginia Transformer",
    "MPI Morheat",
    "Areias",
    "Xometry",
    # Specific Antora channel and folder IDs
    "C0ASTTRRF47",
    "C0ATR4S9WCS",
    "1Ekb76OLfHKxj3SuBN3jANgDS_Nn5scyR",
    # Specific Antora email/domain patterns
    "@antora.energy",
    "antora.energy",
    "vincent.calianno",
    # Domain-leaking field names (specific stack vendors)
    "gmail_thread_id",
    "gmail_message_id",
    "drive_folder_path",
    "drive_path",
    # Domain-leaking role names that should be configurable per deployment
    "owner_scm",
    "last_antora_version_sent",
    "lrs_status",
    "last_lrs_sent_date",
    # Antora-specific role and contract terminology
    "SCM",        # Antora role name; use "owner" or "tenant owner" in layer_b
    "supplier",   # Antora domain term; use "counterparty" in layer_b
    "vendor",     # synonym for supplier; use "counterparty" in layer_b
    "MEPA",       # Antora contract type; use "generic-agreement" in layer_b tests
    "MPA",        # Antora contract type; use "generic-agreement" in layer_b tests
]

# Patterns that should not appear in layer_b
ANTORA_PATTERNS = [
    # Antora-domain emails
    r"[a-zA-Z0-9_.-]+@antora\.energy",
]


def check_no_layer_c_imports():
    """Verify layer_b code never imports from layer_c_antora."""
    violations = []
    for py_file in LAYER_B.rglob("*.py"):
        text = py_file.read_text()
        # Look for any import line referencing layer_c or antora
        for line_no, line in enumerate(text.split("\n"), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if ("from acp.layer_c" in stripped or
                    "import acp.layer_c" in stripped or
                    "from layer_c" in stripped or
                    "import layer_c" in stripped):
                violations.append(
                    f"  {py_file.relative_to(ROOT)}:{line_no}  {stripped}"
                )
    return violations


def check_no_antora_strings_in_layer_b():
    """Verify no Antora-specific strings appear in layer_b code or tests."""
    violations = []
    for py_file in LAYER_B.rglob("*.py"):
        text = py_file.read_text()
        for forbidden in ANTORA_FORBIDDEN:
            # Case-sensitive exact substring check; skip if in a code-fence comment that's clearly a counterexample
            if forbidden in text:
                # Allow the docstring examples in the SheetsLedger stub — but that's in layer_c so not relevant here
                lines = text.split("\n")
                for line_no, line in enumerate(lines, start=1):
                    if forbidden in line:
                        # Allow if line is part of the discipline-check itself
                        if py_file.name == "discipline_check.py":
                            continue
                        violations.append(
                            f"  {py_file.relative_to(ROOT)}:{line_no}  contains '{forbidden}'"
                        )

        for pattern in ANTORA_PATTERNS:
            for match in re.finditer(pattern, text):
                # Compute line number
                line_no = text[:match.start()].count("\n") + 1
                violations.append(
                    f"  {py_file.relative_to(ROOT)}:{line_no}  matches pattern '{pattern}'"
                )
    return violations


def check_workflow_id_at_emit_sites():
    """Verify StateEvent( and NegotiationRow( constructors always include workflow_id.

    Uses parenthesis-depth tracking to extract each full constructor call, then
    checks that 'workflow_id' appears within it. Comment lines are skipped.
    Note: string literals containing unbalanced parentheses could cause false
    results — avoid those in constructor arguments.
    """
    CONSTRUCTORS = ("StateEvent(", "NegotiationRow(")
    violations = []
    for py_file in LAYER_B.rglob("*.py"):
        text = py_file.read_text()
        for constructor in CONSTRUCTORS:
            search_start = 0
            while True:
                pos = text.find(constructor, search_start)
                if pos == -1:
                    break
                # Skip occurrences that appear in comment lines
                line_start = text.rfind('\n', 0, pos) + 1
                if text[line_start:pos].lstrip().startswith('#'):
                    search_start = pos + len(constructor)
                    continue
                # Extract the full constructor call via paren-depth tracking
                depth = 1
                i = pos + len(constructor)
                while i < len(text) and depth > 0:
                    if text[i] == '(':
                        depth += 1
                    elif text[i] == ')':
                        depth -= 1
                    i += 1
                call_text = text[pos:i]
                # If the call uses **-spreading (e.g. NegotiationRow(**defaults)),
                # trust that workflow_id is in the spread dict — dict contents
                # cannot be traced statically.
                if re.search(r'\*\*[a-zA-Z_]', call_text):
                    search_start = i
                    continue
                if 'workflow_id' not in call_text:
                    line_no = text[:pos].count('\n') + 1
                    violations.append(
                        f"  {py_file.relative_to(ROOT)}:{line_no}"
                        f"  {constructor[:-1]}(...) missing workflow_id"
                    )
                search_start = i
    return violations


def check_adapter_directory_structure():
    """Verify adapter abstract interfaces exist for external integrations."""
    required = [
        LAYER_B / "core" / "adapters" / "ledger_adapter.py",
        LAYER_B / "core" / "adapters" / "audit_adapter.py",
    ]
    missing = [p for p in required if not p.exists()]
    return [f"  MISSING: {p.relative_to(ROOT)}" for p in missing]


def main():
    print("=" * 70)
    print("ACP Implementation Discipline Check")
    print("Per Architecture Spec v2.4 Section 13.7")
    print("=" * 70)

    all_violations = []

    print("\n[1/4] Checking layer_b imports for layer_c references...")
    v = check_no_layer_c_imports()
    if v:
        print(f"  FAIL: {len(v)} import boundary violation(s):")
        for line in v:
            print(line)
        all_violations.extend(v)
    else:
        print("  PASS: layer_b has no imports from layer_c_antora")

    print("\n[2/4] Checking for Antora-specific strings in layer_b...")
    v = check_no_antora_strings_in_layer_b()
    if v:
        print(f"  FAIL: {len(v)} Antora-specific string violation(s):")
        for line in v:
            print(line)
        all_violations.extend(v)
    else:
        print("  PASS: layer_b contains no Antora-specific strings")

    print("\n[3/4] Checking required adapter interfaces exist...")
    v = check_adapter_directory_structure()
    if v:
        print(f"  FAIL: missing required adapter file(s):")
        for line in v:
            print(line)
        all_violations.extend(v)
    else:
        print("  PASS: required adapter interfaces present")

    print("\n[4/4] Checking workflow_id at StateEvent and NegotiationRow emit sites...")
    v = check_workflow_id_at_emit_sites()
    if v:
        print(f"  FAIL: {len(v)} constructor(s) missing workflow_id:")
        for line in v:
            print(line)
        all_violations.extend(v)
    else:
        print("  PASS: all StateEvent and NegotiationRow constructors include workflow_id")

    print("\n" + "=" * 70)
    if all_violations:
        print(f"DISCIPLINE CHECK FAILED — {len(all_violations)} violation(s)")
        print("=" * 70)
        return 1
    else:
        print("DISCIPLINE CHECK PASSED")
        print("=" * 70)
        return 0


if __name__ == "__main__":
    sys.exit(main())
