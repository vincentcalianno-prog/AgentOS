"""Dry-run harness for Workflow #2 report triage.

Reads sanitized fixture files from tests/fixtures/report_triage/sanitized/.
Runs the full engine pipeline with stub LLM by default; --real-llm flag
enables live Anthropic API calls.

Never reads from tests/fixtures/report_triage/real/ — real report data is
git-ignored and must never be committed.

Usage:
    python3 run.py [--report REPORT_ID] [--out-dir outputs/<timestamp>]
                   [--llm {stub,real}]

    # Run all configured reports with stub engine (default)
    python3 run.py

    # Run a specific report
    python3 run.py --report vendor_not_yet_accepted

    # Run with real Anthropic API calls (requires ANTHROPIC_API_KEY)
    python3 run.py --llm real --report past_due

    # Specify custom output directory
    python3 run.py --out-dir /tmp/report-triage-dry-run

--llm real requires ANTHROPIC_API_KEY in the environment. Model is controlled
by ACP_LLM_MODEL (default: claude-sonnet-4-6). On auth error or unknown model
the harness prints a STOP message and exits 1.

Exit codes:
    0 — pipeline completed without errors
    1 — pipeline error or missing required fixture

Outputs produced (all in <out-dir>/):
    tracker_diff.json      — per-item classification (new/aging/escalated/conflict)
    owner_fanout.json      — items grouped by owner
    draft_actions.json     — drafted action proposals per item
    audit_log.json         — all engine events for this run
    run_manifest.json      — run metadata (report_id, timestamps, llm_mode)
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on path
_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_ROOT = _REPO_ROOT / "tests" / "fixtures" / "report_triage"
_SANITIZED_DIR = _FIXTURES_ROOT / "sanitized"
_REAL_DIR = _FIXTURES_ROOT / "real"   # git-ignored; must never be read here

# Layer C config root for Antora
_LAYER_C = _REPO_ROOT / "acp" / "layer_c_antora"
_REPORT_CONFIG_DIR = _LAYER_C / "report_triage" / "reports"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run harness for Workflow #2 Report Triage"
    )
    parser.add_argument(
        "--report",
        metavar="REPORT_ID",
        help="Run a specific report by report_id. Omit to run all configured reports.",
    )
    parser.add_argument(
        "--out-dir",
        metavar="DIR",
        default=None,
        help="Output directory. Defaults to outputs/<timestamp>/",
    )
    parser.add_argument(
        "--llm",
        choices=["stub", "real"],
        default="stub",
        help="LLM mode. 'real' requires ANTHROPIC_API_KEY.",
    )
    return parser.parse_args()


def _resolve_output_dir(out_dir_arg: str | None) -> Path:
    if out_dir_arg:
        return Path(out_dir_arg)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(__file__).parent / "outputs" / ts


def _write_manifest(out_dir: Path, args: argparse.Namespace, run_id: str) -> None:
    manifest = {
        "run_id": run_id,
        "workflow": "report_triage",
        "report_id": args.report or "all",
        "llm_mode": args.llm,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "fixture_dir": str(_SANITIZED_DIR),
    }
    (out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def main() -> int:
    args = _parse_args()
    run_id = str(uuid.uuid4())
    out_dir = _resolve_output_dir(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[report_triage_dry_run] run_id={run_id}")
    print(f"[report_triage_dry_run] output → {out_dir}")
    print(f"[report_triage_dry_run] llm_mode={args.llm}")

    _write_manifest(out_dir, args, run_id)

    # ---------------------------------------------------------------------------
    # Phase 2: wire the full pipeline here.
    #
    # Pipeline steps (deferred to Phase 2 implementation):
    #   1. Load report config from _REPORT_CONFIG_DIR / <report_id>.yaml
    #   2. Load sanitized fixture bytes from _SANITIZED_DIR / <report_id>.*
    #   3. Parse via TabularParser
    #   4. Normalize via Normalizer (using column_map from report config)
    #   5. Diff against tracker state via Tracker (in-memory storage for dry run)
    #   6. Classify items (new / aging / escalated / conflict)
    #   7. Fan out by owner via fan_out_by_owner()
    #   8. Draft actions via ActionExecutor.draft() for each item
    #   9. Write outputs: tracker_diff.json, owner_fanout.json, draft_actions.json
    #  10. Write audit_log.json
    # ---------------------------------------------------------------------------
    print("[report_triage_dry_run] Pipeline not yet wired — Phase 2 deferred.")
    print(f"[report_triage_dry_run] run_manifest.json written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
