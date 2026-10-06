#!/usr/bin/env python3
"""Build the reviewed, source-only handoff archive. Supports --dry-run without writing a ZIP."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs" / "route-share-local.zip"

# Explicit files and source trees only. Work databases, browser screenshots,
# build outputs, dependency installs, environment files, and credentials are out.
FILES = (
    "README.md",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    ".railwayignore",
    "Dockerfile",
    "server.py",
    "hosted.py",
    "gunicorn.conf.py",
    "requirements.txt",
    "requirements-dev.txt",
    "design-qa.md",
    "mobile/README.md",
    "mobile/.env.example",
    "mobile/.gitignore",
    "mobile/BUILD_EVIDENCE.md",
    "mobile/eas.json",
    "mobile/app.config.js",
    "mobile/index.ts",
    "mobile/package.json",
    "mobile/package-lock.json",
    "mobile/tsconfig.json",
)
TREES = (
    "app",
    "docs",
    "static",
    "tests",
    "scripts",
    "mobile/src",
    "mobile/locales",
    "mobile/plugins",
    "mobile/scripts",
    "mobile/assets",
)
EXCLUDED_PARTS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "node_modules", "dist", "build", "work", "target", ".expo",
}
EXCLUDED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pyc", ".pyo", ".hbc", ".map", ".zip"}
EXCLUDED_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}


def _is_safe_source(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    relative = path.relative_to(ROOT)
    vendored_runtime = relative.as_posix().startswith("static/vendor/maplibre/maplibre-gl/dist/")
    excluded_parts = EXCLUDED_PARTS - {"dist"} if vendored_runtime else EXCLUDED_PARTS
    if any(part in excluded_parts for part in relative.parts):
        return False
    if path.name in EXCLUDED_NAMES or (path.name.startswith(".env.") and path.name != ".env.example"):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    lowered = path.name.lower()
    if any(secret in lowered for secret in ("secret", "credential", "private-key", "private_key")):
        return False
    return True


def collect_files() -> list[Path]:
    selected: set[Path] = set()
    for name in FILES:
        path = ROOT / name
        if not path.exists() or not _is_safe_source(path):
            raise SystemExit(f"Required allowlisted source is missing or unsafe: {name}")
        selected.add(path)
    for name in TREES:
        directory = ROOT / name
        if not directory.is_dir():
            raise SystemExit(f"Required source directory is missing: {name}")
        for path in directory.rglob("*"):
            if _is_safe_source(path):
                selected.add(path)
    return sorted(selected, key=lambda p: p.relative_to(ROOT).as_posix())


def _archive_name(path: Path) -> str:
    return PurePosixPath(path.relative_to(ROOT).as_posix()).as_posix()


def _manifest(files: list[Path]) -> bytes:
    rows = ["Route Share source package manifest", "Generated file list with SHA-256:"]
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {_archive_name(path)}")
    rows.append("Excluded by design: work data, databases, secrets, environment files, node_modules, dist/build outputs, and screenshots.")
    return ("\n".join(rows) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="list reviewed files; do not create an archive")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="archive path (default: outputs/route-share-local.zip)")
    args = parser.parse_args()

    files = collect_files()
    total_bytes = sum(path.stat().st_size for path in files)
    if args.dry_run:
        print(f"Dry run: {len(files)} files, {total_bytes:,} source bytes")
        for path in files:
            print(_archive_name(path))
        return 0

    output = args.output.expanduser().resolve()
    outputs_root = (ROOT / "outputs").resolve()
    if not output.is_relative_to(outputs_root) or output.suffix.lower() != ".zip":
        raise SystemExit("Output must be a .zip file inside the project outputs directory.")
    if output in files:
        raise SystemExit("Output archive cannot overwrite an allowlisted input.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            info = ZipInfo(_archive_name(path), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
        info = ZipInfo("PACKAGE-MANIFEST.txt", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        archive.writestr(info, _manifest(files))
    print(f"Created {output} with {len(files)} allowlisted files ({total_bytes:,} uncompressed bytes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
