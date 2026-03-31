"""
Pipeline runner wrapper for programmatic use.
Uses shared orchestrator logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .config import OUTPUT_DIR, PLAN_DIR
from .orchestrator import run_generation_pipeline


def run_pipeline(yaml_path: Path) -> Dict:
    """Run the default direct-build pipeline from a YAML plan file."""
    return run_generation_pipeline(
        Path(yaml_path),
        validate_strict=False,
        cleanup_first=True,
        auto_archive=False,
    )


def save_yaml_to_plan_dir(yaml_content: str, filename: str) -> Path:
    """Save YAML content to Plan directory."""
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    file_path = PLAN_DIR / filename
    file_path.write_text(yaml_content, encoding="utf-8")
    print(f"Saved YAML to {file_path}")
    return file_path


def get_fit_files_from_output() -> List[Path]:
    """Get all FIT files from Output_fit directory."""
    if not OUTPUT_DIR.exists():
        return []
    return sorted(OUTPUT_DIR.glob("*.fit"))
