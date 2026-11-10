"""Build and Packaging Script for ElcAgent Portable Distribution (Phase 30: D-30-06, D-30-07, D-30-08).

Functions:
- build_manifest: Enforces strict exclusion rules (no calibration files, no config.json with keys, no .env, no *.json except config.template.json).
- verify_sha256: Verifies agent-desktop.exe against AGENT_DESKTOP_SHA256 env var (fail-closed).
- make_zip: Creates one-folder zip archive rooted at ElcAgent/.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple


class BuildIntegrityError(RuntimeError):
    """Raised when packaging integrity checks fail (e.g. SHA256 mismatch, forbidden files)."""


def is_forbidden_file(file_path: str) -> bool:
    """Check if file matches forbidden inclusion patterns."""
    normalized = file_path.replace("\\", "/").strip()
    parts = normalized.split("/")
    filename = parts[-1]

    # Exclude calibration files and directories
    if "calibration" in parts or any(p.startswith("calibration") for p in parts):
        return True

    # Exclude .env files
    if filename == ".env" or filename.startswith(".env.") or ".env" in parts:
        return True

    # Exclude config.json
    if filename == "config.json":
        return True

    # Exclude any *.json except config.template.json
    if filename.endswith(".json") and filename != "config.template.json":
        return True

    return False


def build_manifest(files: List[str]) -> Tuple[List[str], List[str]]:
    """Partition input files into included and excluded lists based on packaging rules."""
    included: List[str] = []
    excluded: List[str] = []

    for f in files:
        if is_forbidden_file(f):
            excluded.append(f)
        else:
            included.append(f)

    return included, excluded


def verify_sha256(path: Path | str, expected: Optional[str] = None) -> bool:
    """Verify SHA256 hash of agent-desktop executable against expected hash.

    Fail-closed: If expected hash is not provided and AGENT_DESKTOP_SHA256 is empty, raises BuildIntegrityError.
    """
    target_path = Path(path)
    if not target_path.exists() or not target_path.is_file():
        raise BuildIntegrityError(f"Target binary file not found: {target_path}")

    expected_hash = expected or os.environ.get("AGENT_DESKTOP_SHA256", "").strip()
    if not expected_hash:
        raise BuildIntegrityError(
            "AGENT_DESKTOP_SHA256 environment variable is not set (fail-closed). "
            "Build cannot proceed without verified binary integrity."
        )

    hasher = hashlib.sha256()
    with open(target_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    actual_hash = hasher.hexdigest().lower()

    if actual_hash != expected_hash.lower():
        raise BuildIntegrityError(
            f"SHA256 mismatch for {target_path.name}: "
            f"expected {expected_hash.lower()}, got {actual_hash}"
        )

    return True


def make_zip(dist_dir: Path, out_path: Path) -> Path:
    """Package dist_dir contents into a zip archive with top-level folder ElcAgent/."""
    target_dist = Path(dist_dir)
    target_out = Path(out_path)
    target_out.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(target_out, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(target_dist):
            for file in sorted(files):
                full_path = Path(root) / file
                rel_path = full_path.relative_to(target_dist)
                # Ensure top-level directory in zip is ElcAgent/
                archive_name = str(Path("ElcAgent") / rel_path).replace("\\", "/")
                zf.write(full_path, arcname=archive_name)

    return target_out


def build() -> None:
    """Main build entry point."""
    print("ElcAgent build script started.")
    if sys.platform != "win32":
        print("Note: Running on non-Windows environment. Windows binary packaging is executed on Windows workstation.")
        return

    # Windows build execution via PyInstaller
    spec_path = Path(__file__).resolve().parent.parent / "deploy" / "windows_agent" / "ElcAgent.spec"
    import subprocess
    subprocess.check_call(["uv", "run", "pyinstaller", "--clean", str(spec_path)])


if __name__ == "__main__":
    build()
