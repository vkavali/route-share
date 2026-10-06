#!/usr/bin/env python3
"""Stage an explicit, runtime-only Railway Docker build context under work/."""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "work" / "railway-deploy"
FILES = (
    ".dockerignore",
    ".railwayignore",
    "Dockerfile",
    "requirements.txt",
    "hosted.py",
    "gunicorn.conf.py",
)
TREES = ("app", "static")
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", "build"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".env"}
RUNTIME_ASSET_PNGS = {
    "static/assets/higgsfield-empty-reference.png",
    "static/assets/higgsfield-signin-reference.png",
}


def source_files() -> list[Path]:
    files = [ROOT / name for name in FILES]
    for directory_name in TREES:
        directory = ROOT / directory_name
        if not directory.is_dir():
            raise SystemExit(f"Required runtime source directory is missing: {directory_name}")
        for source in directory.rglob("*"):
            if source.is_symlink():
                raise SystemExit(f"Refusing symlink in runtime source: {source.relative_to(ROOT)}")
            if not source.is_file():
                continue
            relative = source.relative_to(ROOT)
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            if "dist" in relative.parts and relative.parts[:2] != ("static", "vendor"):
                continue
            if relative.as_posix() == "static/maplibre-gl-worker.mjs":
                continue
            if (
                relative.parts[:2] == ("static", "assets")
                and source.suffix.lower() == ".png"
                and relative.as_posix() not in RUNTIME_ASSET_PNGS
            ):
                continue
            if source.suffix.lower() in EXCLUDED_SUFFIXES or source.name.lower().startswith(".env"):
                continue
            files.append(source)

    unique: dict[str, Path] = {}
    for source in files:
        if source.is_symlink() or not source.is_file():
            raise SystemExit(f"Required runtime file is missing or unsafe: {source.relative_to(ROOT)}")
        relative = source.relative_to(ROOT).as_posix()
        unique[relative] = source
    return [unique[name] for name in sorted(unique)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true", help="replace an existing staged bundle")
    args = parser.parse_args()

    files = source_files()
    target = TARGET
    if target.is_symlink():
        raise SystemExit("Refusing to replace a symlink at work/railway-deploy")
    if target.exists():
        if not args.replace:
            raise SystemExit("work/railway-deploy already exists; review it or pass --replace")
        if target.resolve() != (ROOT / "work" / "railway-deploy").resolve():
            raise SystemExit("Refusing to remove a staged path outside work/railway-deploy")
        shutil.rmtree(target)

    target.mkdir(parents=True)
    manifest: list[str] = ["Route Share Railway runtime source manifest", "SHA-256  BYTES  PATH"]
    byte_count = 0
    for source in files:
        relative = source.relative_to(ROOT)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_bytes()
        destination.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        byte_count += len(content)
        manifest.append(f"{digest}  {len(content):>10}  {relative.as_posix()}")
    (target / "STAGE-MANIFEST.sha256").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(f"Staged {len(files)} allowlisted runtime files ({byte_count:,} source bytes) at {target}")
    print("Manifest: work/railway-deploy/STAGE-MANIFEST.sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
