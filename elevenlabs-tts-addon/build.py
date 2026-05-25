"""Reproducible build script for the ElevenLabs TTS NVDA add-on.

Usage:
    py -3 build.py            # produces ./dist/elevenlabsTTS-<version>.nvda-addon
    py -3 build.py --clean    # wipe ./dist first

This replaces the ad-hoc PowerShell Compress-Archive used in earlier
versions. It reads `version` from manifest.ini so the output filename
always matches what NVDA will install, and it skips junk files (pyc,
__pycache__, .pyo, editor backups) that should never ship.
"""

import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

# Files / dirs that live at the add-on root and must be included in the zip.
INCLUDE_ROOTS = ("manifest.ini", "readme.txt", "CHANGELOG.txt",
                 "synthDrivers", "globalPlugins", "docs", "locale")

# Glob patterns to skip while walking source trees.
SKIP_NAMES = {"__pycache__", ".git", ".idea", ".vscode", "node_modules"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".bak", ".swp", "~")


def read_version() -> str:
    # manifest.ini doesn't use [section] headers, so parse by hand.
    for line in (ROOT / "manifest.ini").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("version") and "=" in line:
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("version not found in manifest.ini")


def should_skip(path: Path) -> bool:
    if path.name in SKIP_NAMES:
        return True
    if any(part in SKIP_NAMES for part in path.parts):
        return True
    if path.name.endswith(SKIP_SUFFIXES):
        return True
    return False


def iter_source_files():
    for top in INCLUDE_ROOTS:
        p = ROOT / top
        if not p.exists():
            continue
        if p.is_file():
            yield p
            continue
        for sub in p.rglob("*"):
            if sub.is_file() and not should_skip(sub):
                yield sub


def build(clean: bool = False) -> Path:
    if clean and DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(exist_ok=True)
    version = read_version()
    out = DIST / f"elevenlabsTTS-{version}.nvda-addon"
    if out.exists():
        out.unlink()

    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in iter_source_files():
            rel = f.relative_to(ROOT).as_posix()
            zf.write(f, rel)
            total += 1
    print(f"built {out.name} ({total} files, {out.stat().st_size / 1024:.1f} KB)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="wipe dist/ before building")
    args = ap.parse_args()
    out = build(clean=args.clean)
    print(out)


if __name__ == "__main__":
    sys.exit(main())
