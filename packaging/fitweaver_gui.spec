# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FitWeaver's desktop GUI (FitWeaver.exe).

Ships alongside garmin-fit-cli.exe (see fitweaver_cli.spec) in the same
folder -- the GUI's sidebar actions shell out to that sibling exe since a
frozen exe can't be re-run with `-m` like a real Python interpreter.

Deliberately a SEPARATE spec file (not two Analysis/PYZ blocks in one spec):
PyInstaller names each Analysis's intermediate PYZ archive "PYZ-01.pyz"
within its work directory, so two Analysis blocks sharing one spec's default
work directory silently overwrite each other's PYZ on disk -- the second
build's PYZ clobbers the first's, and the first EXE ends up embedding the
wrong (or missing) modules with no build-time warning. Separate spec files
get separate work directories (named after each spec's basename) for free.

Both this and fitweaver_cli.spec use onefile mode, which is safe here
because writable state (Plan/, profiles/, .gui_session.json, ...) is
resolved from sys.executable's parent directory (see config.py /
fitweaver_gui.py), which stays stable across onefile's per-launch temp
extraction -- unlike sys._MEIPASS or __file__.

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

# LLM prompt contract/examples/input-format rules read via Path(__file__).parent in
# garmin_fit/llm/prompt.py -- read-only bundled resources, not writable
# state, so PyInstaller's own module-relative path resolution handles them
# correctly once they're actually included via datas=.
llm_datas = collect_data_files("garmin_fit.llm", includes=["*.yaml", "*.txt", "*.md"])
ctk_datas = collect_data_files("customtkinter")

# fitweaver_gui.py imports most of garmin_fit lazily (inside methods, e.g.
# `from garmin_fit.plan_store import PlanStore`). PyInstaller's static
# bytecode analysis can silently miss some of these -- force-include every
# garmin_fit submodule so newly added modules can't hit the same silent gap.
garmin_fit_submodules = [m for m in collect_submodules("garmin_fit") if _app_module(m)]

a = Analysis(
    [str(REPO_ROOT / "fitweaver_gui.py")],
    pathex=[str(SRC_DIR)],
    datas=llm_datas + ctk_datas,
    hiddenimports=garmin_fit_submodules,
    excludes=HEAVY_EXCLUDES + list(SERVICE_MODULES),
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FitWeaver",
    console=False,
)
