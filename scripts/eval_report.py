"""CLI entrypoint to generate all Phase 3 evaluation reports, tables, SVGs, and docs."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.eval.report import generate_all_reports


def main():
    print("=== GENERATING PHASE 3 EVALUATION REPORTS & ASSETS ===")
    summary = generate_all_reports()
    print("Reports generated successfully:")
    print(f"  - eval/summary.json")
    print(f"  - eval/tables/*.csv")
    print(f"  - eval/figures/*.svg")
    print(f"  - frontend/public/eval/*.json")
    print(f"  - docs/EVALUATION.md")
    print(f"  - docs/REQUIREMENTS_MATRIX.md")


if __name__ == "__main__":
    main()
