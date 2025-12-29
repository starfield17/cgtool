"""
cgtool package entry point.

Supports:
  - python -m cgtool [args...]
  - PyInstaller bundled executable (where __package__ can be empty)
Behavior:
  - Default: run CLI entry (same as console script: cgtool = cgtool.cli:main)
  - If you want GUI by default, set CGTOOL_MODE=gui
  - You can force GUI with: --gui
  - You can force CLI with: --cli
"""

from __future__ import annotations

import os
import sys
from typing import List


def _ensure_import_path() -> None:
    """
    When executed by PyInstaller, __package__ may be empty and relative imports break.
    Ensure project root is on sys.path so absolute imports like `cgtool.cli` work.
    This is safe even in normal `python -m cgtool` runs.
    """
    if __package__:
        return

    pkg_dir = os.path.dirname(os.path.abspath(__file__))  # .../src/cgtool
    src_dir = os.path.dirname(pkg_dir)                    # .../src
    proj_root = os.path.dirname(src_dir)                  # project root

    # Prefer src_dir so imports resolve to editable sources if present.
    for p in (src_dir, proj_root):
        if p and p not in sys.path:
            sys.path.insert(0, p)


def _pick_mode(argv: List[str]) -> str:
    """
    Decide run mode: 'cli' or 'gui'
    Priority:
      1) explicit flags: --cli / --gui
      2) env var: CGTOOL_MODE=cli|gui
      3) default: cli
    """
    if "--gui" in argv:
        return "gui"
    if "--cli" in argv:
        return "cli"

    mode = os.environ.get("CGTOOL_MODE", "").strip().lower()
    if mode in ("cli", "gui"):
        return mode

    return "cli"


def main(argv: List[str] | None = None) -> None:
    _ensure_import_path()

    if argv is None:
        argv = sys.argv[1:]

    mode = _pick_mode(argv)

    # Remove our mode flags so downstream parsers (argparse/typer/click) won't choke.
    cleaned = [a for a in argv if a not in ("--cli", "--gui")]
    sys.argv = [sys.argv[0], *cleaned]

    if mode == "gui":
        # GUI entry
        try:
            from cgtool.gui import run_gui
        except Exception as e:
            # Common case: GUI deps not installed in minimal environments
            msg = str(e)
            print("Failed to start GUI mode.", file=sys.stderr)
            print(f"Reason: {msg}", file=sys.stderr)
            print("", file=sys.stderr)
            print("Tips:", file=sys.stderr)
            print("  - Ensure GUI dependencies are installed (e.g., PySide6).", file=sys.stderr)
            print("  - Or run CLI mode:", file=sys.stderr)
            print("      python -m cgtool --cli ...", file=sys.stderr)
            sys.exit(1)

        run_gui()
        return

    # CLI entry (default)
    from cgtool.cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
