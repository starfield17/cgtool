# src/cgtool/__main__.py
from __future__ import annotations

import sys


CLI_FORCE_FLAGS = {
    "--cli",        # preferred
    "-c",           # short
    "--console",    # alias
    "--no-gui",     # alias
}


def _wants_cli(argv: list[str]) -> bool:
    """
    Decide whether to run CLI.

    Rules:
    - Default: GUI
    - Run CLI only if user explicitly passes a force flag:
        --cli | -c | --console | --no-gui
    - Also support: `python -m cgtool cli ...` (subcommand style)
    """
    if any(flag in argv for flag in CLI_FORCE_FLAGS):
        return True
    if len(argv) >= 2 and argv[1].lower() == "cli":
        return True
    return False


def _strip_cli_markers(argv: list[str]) -> list[str]:
    """
    Remove markers that are only used to trigger CLI mode, so downstream
    argparse in cgtool.cli doesn't see unknown arguments.
    """
    cleaned: list[str] = []
    skip_next = False

    for i, a in enumerate(argv):
        if skip_next:
            skip_next = False
            continue

        # drop standalone flags
        if a in CLI_FORCE_FLAGS:
            continue

        # drop subcommand marker: `python -m cgtool cli ...`
        if i == 1 and a.lower() == "cli":
            continue

        cleaned.append(a)

    return cleaned


def _run_cli() -> None:
    from cgtool.cli import main as cli_main

    # Remove `--cli` / `cli` marker etc. so CLI parser gets clean argv.
    sys.argv = _strip_cli_markers(sys.argv)
    cli_main()


def _run_gui() -> None:
    """
    Launch GUI. If GUI dependencies are missing, print a clear message and exit.
    """
    try:
        from cgtool.gui import run_gui
    except Exception as e:
        msg = str(e)

        # Common missing GUI deps (adjust if you use different GUI toolkit)
        likely_gui_missing = any(
            key in msg
            for key in ("PySide6", "PyQt5", "PyQt6", "tkinter", "Qt", "gui")
        )

        if likely_gui_missing:
            print("=" * 60)
            print("GUI mode is not available in this environment.")
            print(f"Reason: {e.__class__.__name__}: {e}")
            print("")
            print("To run in CLI mode:")
            print("  python -m cgtool --cli --help")
            print("  (or) cgtool --help")
            print("=" * 60)
            raise SystemExit(1)

        # Unknown error: re-raise for a real traceback
        raise

    run_gui()


def main() -> None:
    if _wants_cli(sys.argv):
        _run_cli()
    else:
        _run_gui()


if __name__ == "__main__":
    main()
