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

    print("\n[1/3] Checking layer_b imports for layer_c references...")
    v = check_no_layer_c_imports()
    if v:
        print(f"  FAIL: {len(v)} import boundary violation(s):")
        for line in v:
            print(line)
        all_violations.extend(v)
    else:
        print("  PASS: layer_b has no imports from layer_c_antora")

    print("\n[2/3] Checking for Antora-specific strings in layer_b...")
    v = check_no_antora_strings_in_layer_b()
    if v:
        print(f"  FAIL: {len(v)} Antora-specific string violation(s):")
        for line in v:
            print(line)
        all_violations.extend(v)
    else:
        print("  PASS: layer_b contains no Antora-specific strings")

    print("\n[3/3] Checking required adapter interfaces exist...")
    v = check_adapter_directory_structure()
    if v:
        print(f"  FAIL: missing required adapter file(s):")
        for line in v:
            print(line)
        all_violations.extend(v)
    else:
        print("  PASS: required adapter interfaces present")

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
