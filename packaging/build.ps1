# Builds dist/FitWeaver.exe + dist/garmin-fit-cli.exe. Run from the repo root
# or from anywhere -- paths below are anchored to this script's location.
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Stage = Join-Path $RepoRoot "build\stage"

Push-Location $RepoRoot
try {
    pip install -e ".[garmin-calendar,build]"
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

    # Build from an isolated staging copy, not the live source tree. The
    # repo root also has a garmin_fit/ compatibility bridge package (see
    # CLAUDE.md: "alias bridge layer, DO NOT edit directly") that only
    # contains __init__.py and an empty llm/ dir -- it works at runtime via
    # a __path__.append() trick pointing at src/garmin_fit, but PyInstaller
    # auto-adds fitweaver_gui.py's own directory (the repo root) to its
    # search path, and its resolution of *lazily* imported garmin_fit
    # submodules (fitweaver_gui.py imports almost all of them inside method
    # bodies, not at module level) doesn't honor that runtime __path__
    # trick -- it silently resolves against the near-empty bridge directory
    # instead, dropping modules like plan_store/workout_builder from the
    # frozen build with no build-time error. Building from a copy that has
    # no root-level garmin_fit/ at all sidesteps the ambiguity entirely.
    if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
    New-Item -ItemType Directory -Force -Path $Stage | Out-Null
    Copy-Item -Recurse -Path (Join-Path $RepoRoot "src") -Destination (Join-Path $Stage "src")
    Copy-Item -Path (Join-Path $RepoRoot "fitweaver_gui.py") -Destination $Stage
    New-Item -ItemType Directory -Force -Path (Join-Path $Stage "packaging") | Out-Null
    Copy-Item -Path (Join-Path $RepoRoot "packaging\cli_entry.py") -Destination (Join-Path $Stage "packaging")
    Copy-Item -Path (Join-Path $RepoRoot "packaging\fitweaver_gui.spec") -Destination (Join-Path $Stage "packaging")
    Copy-Item -Path (Join-Path $RepoRoot "packaging\fitweaver_cli.spec") -Destination (Join-Path $Stage "packaging")

    Push-Location $Stage
    try {
        # Invoked as `python -m PyInstaller` rather than the bare
        # `pyinstaller` command: pip installs the console-script wrapper
        # into a Scripts/ directory that isn't always on PATH (seen in
        # practice as "pyinstaller: command not found" even right after a
        # successful `pip install`), while `python` itself reliably is.
        #
        # Two separate spec files (not two Analysis blocks in one spec) so
        # each gets its own PyInstaller work directory -- see
        # fitweaver_gui.spec's docstring for why sharing one causes
        # silently-corrupted onefile exes. Each also gets its OWN --workpath
        # root (build\gui, build\cli), not a shared "build" parent: running
        # two PyInstaller invocations back-to-back against subdirectories of
        # the same parent directory has been observed to hit a Windows
        # file-locking race (FileNotFoundError creating base_library.zip in
        # the second build's subdirectory, likely AV/OneDrive scanning the
        # first build's freshly-written files) -- fully separate roots
        # avoid any contention between the two.
        python -m PyInstaller packaging/fitweaver_gui.spec --distpath "$RepoRoot\dist" --workpath build\gui --noconfirm
        if ($LASTEXITCODE -ne 0) { throw "pyinstaller build failed (gui)" }

        python -m PyInstaller packaging/fitweaver_cli.spec --distpath "$RepoRoot\dist" --workpath build\cli --noconfirm
        if ($LASTEXITCODE -ne 0) { throw "pyinstaller build failed (cli)" }
    }
    finally {
        Pop-Location
    }

    Write-Host "Built dist/FitWeaver.exe and dist/garmin-fit-cli.exe -- ship them together in the same folder."
}
finally {
    Pop-Location
}
