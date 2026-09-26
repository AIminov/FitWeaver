# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the garmin-fit-cli.exe sibling exe.

See fitweaver_gui.spec for why this is a separate spec file rather than a
second Analysis/PYZ block sharing that spec (PYZ work-directory collision).

Build with: packaging/build.ps1 (or `pyinstaller packaging/fitweaver_gui.spec
packaging/fitweaver_cli.spec` from the repo root after
`pip install -e ".[garmin-calendar,build]"`).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

REPO_ROOT = Path(SPECPATH).resolve().parent
SRC_DIR = REPO_ROOT / "src"

block_cipher = None

# The desktop exes never run the Telegram bot or the Plan API (those stay
# Python services), and several heavy packages are only optional extras of
# dependencies (openai's pandas/numpy helpers, httpx's CLI via rich/pygments,
# pytest pulled in through anyio). Leaving them out shrinks the onefile exe,
# which is unpacked on every start.
SERVICE_MODULES = ("garmin_fit.telegram_bot", "garmin_fit.bot", "garmin_fit.api", "garmin_fit.api_cli")
HEAVY_EXCLUDES = [
    "telegram", "fastapi", "starlette", "uvicorn",
    "pandas", "numpy", "openpyxl", "xlsxwriter", "lxml", "matplotlib",
    "pytest", "_pytest", "py", "pygments", "rich", "IPython",
]


def _app_module(name):
    return not any(name == m or name.startswith(m + ".") for m in SERVICE_MODULES)

llm_datas = collect_data_files("garmin_fit.llm", includes=["*.yaml", "*.txt", "*.md"])

# The GUI-only modules are dropped from the force-include list, and the toolkits
# they reach for are excluded outright. gui_theme.load_customtkinter() does a
# lazy `import customtkinter` that PyInstaller's static analysis still follows,
# so a blanket collect_submodules("garmin_fit") dragged all of customtkinter and
# tkinter into this console exe -- which never touches either.
_GUI_ONLY = {"garmin_fit.gui_theme", "garmin_fit.gui_validation"}
garmin_fit_submodules = [
    m for m in collect_submodules("garmin_fit") if m not in _GUI_ONLY and _app_module(m)
]

a = Analysis(
    [str(REPO_ROOT / "packaging" / "cli_entry.py")],
    pathex=[str(SRC_DIR)],
    datas=llm_datas,
    hiddenimports=garmin_fit_submodules,
    excludes=["tkinter", "_tkinter", "customtkinter", "PIL"] + HEAVY_EXCLUDES + list(SERVICE_MODULES),
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="garmin-fit-cli",
    console=True,
)
