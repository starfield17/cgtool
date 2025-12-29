"""
cgtool/__main__.py
Entry point for running with python -m cgtool

Default behavior:
- Launches GUI if PySide6 is available
- Falls back to CLI if PySide6 is not installed
- Use --cli flag to force CLI mode
"""

import sys


def main():
    """Main entry point"""
    # Check for --cli flag
    use_cli = "--cli" in sys.argv
    
    if use_cli:
        # Remove --cli from argv before passing to CLI
        sys.argv = [arg for arg in sys.argv if arg != "--cli"]
        from .cli import main as cli_main
        cli_main()
        return
    
    # Try to launch GUI
    try:
        from .gui import run_gui
        run_gui()
    except ImportError as e:
        # PySide6 not installed
        if "PySide6" in str(e) or "gui" in str(e):
            print("=" * 60)
            print("GUI mode requires PySide6. Install with:")
            print("  pip install cgtool[gui]")
            print("  or: pip install PySide6")
            print("")
            print("To use CLI mode directly:")
            print("  python -m cgtool --cli <command>")
            print("  or: cgtool <command>")
            print("=" * 60)
            sys.exit(1)
        else:
            raise


if __name__ == "__main__":
    main()
