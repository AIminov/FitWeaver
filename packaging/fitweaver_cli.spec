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

llm_datas = collect_data_files("garmin_fit.llm", includes=["*.yaml", "*.txt"])
garmin_fit_submodules = collect_submodules("garmin_fit")

a = Analysis(
    [str(REPO_ROOT / "packaging" / "cli_entry.py")],
    pathex=[str(SRC_DIR)],
    datas=llm_datas,
    hiddenimports=garmin_fit_submodules,
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
