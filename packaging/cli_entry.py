"""PyInstaller entry point for the garmin-fit-cli.exe sibling exe.

Wraps garmin_fit.cli:main directly rather than relying on a venv-generated
console-script wrapper, which PyInstaller can't reliably target across
machines.
"""

import sys

from garmin_fit.cli import main

if __name__ == "__main__":
    sys.exit(main())
