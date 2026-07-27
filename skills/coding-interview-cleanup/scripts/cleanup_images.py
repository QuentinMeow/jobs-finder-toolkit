#!/usr/bin/env python3
"""Create verified screenshot backups and audit a cleaned interview problem folder."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}
BACKUP_DIR_NAME = "originals_backup"
CHECKSUM_FILE_NAME = "SHA256SUMS.txt"
CURATED_DIR_NAMES = ("question_description", "code_setup")


def image_files(directory: Path, recursive: bool = False) -> list[Path]:
    """Return image files in stable filename order."""
    if not directory.exists():
        return []
    iterator = directory.rglob("*") if recursive else directory.iterdir()
    return sorted(
        (path for path in iterator if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES),
        key=lambda path: str(path).lower(),
    )


def sha256_file(path: Path) -> str:
    """Hash a file without loading the whole image into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_destination(backup_dir: Path, source: Path, digest: str) -> Path:
    """Choose a non-overwriting destination for a new unique source image."""
    candidate = backup_dir / source.name
    if not candidate.exists():
        return candidate
    if sha256_file(candidate) == digest:
        return candidate
    return backup_dir / f"{source.stem}__{digest[:8]}{source.suffix}"


def write_checksums(backup_dir: Path) -> Path:
    """Write a stable checksum manifest for all backup images."""
    checksum_path = backup_dir / CHECKSUM_FILE_NAME
    lines = [f"{sha256_file(path)}  {path.name}\n" for path in image_files(backup_dir)]
    checksum_path.write_text("".join(lines), encoding="utf-8")
    return checksum_path


def backup_images(problem_dir: Path, input_dirs: list[Path]) -> int:
    """Copy unique loose images into a byte-verified backup and refresh checksums."""
    problem_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = problem_dir / BACKUP_DIR_NAME
    backup_dir.mkdir(exist_ok=True)

    sources: list[Path] = []
    seen_source_paths: set[Path] = set()
    for directory in [problem_dir, *input_dirs]:
        for path in image_files(directory):
            resolved = path.resolve()
            if resolved not in seen_source_paths:
                sources.append(path)
                seen_source_paths.add(resolved)

    existing_by_hash = {sha256_file(path): path for path in image_files(backup_dir)}
    copied = 0
    skipped = 0

    for source in sources:
        digest = sha256_file(source)
        if digest in existing_by_hash:
            skipped += 1
            continue

        destination = unique_destination(backup_dir, source, digest)
        shutil.copy2(source, destination)
        if sha256_file(destination) != digest:
            destination.unlink(missing_ok=True)
            raise RuntimeError(f"Backup verification failed for {source}")
        existing_by_hash[digest] = destination
        copied += 1

    checksum_path = write_checksums(backup_dir)
    print(f"backup: {copied} copied, {skipped} already present, {len(existing_by_hash)} unique total")
    print(f"checksums: {checksum_path}")
    return 0


def read_checksum_manifest(checksum_path: Path) -> dict[str, str]:
    """Parse a shasum-compatible manifest without accepting unsafe paths."""
    expected: dict[str, str] = {}
    for line_number, raw_line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        parts = raw_line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Malformed checksum line {line_number}: {raw_line}")
        digest, name = parts
        name = name.lstrip("* ")
        if Path(name).name != name:
            raise ValueError(f"Checksum entry must be a filename: {name}")
        expected[name] = digest
    return expected


def find_duplicate_hashes(paths: list[Path]) -> dict[str, list[Path]]:
    """Return only hashes shared by two or more paths."""
    by_hash: dict[str, list[Path]] = {}
    for path in paths:
        by_hash.setdefault(sha256_file(path), []).append(path)
    return {digest: matches for digest, matches in by_hash.items() if len(matches) > 1}


def has_level_suffix(name: str) -> bool:
    """Detect temporary stage suffixes such as level_1 or level-4."""
    lowered = name.lower().replace("-", "_")
    pieces = lowered.split("_")
    return len(pieces) >= 2 and pieces[-2] == "level" and pieces[-1].isdigit()


def audit_problem(problem_dir: Path) -> int:
    """Validate backup integrity and the structure of the curated image set."""
    failures: list[str] = []
    backup_dir = problem_dir / BACKUP_DIR_NAME
    backup_images_found = image_files(backup_dir)
    checksum_path = backup_dir / CHECKSUM_FILE_NAME

    if not backup_images_found:
        failures.append("originals_backup contains no images")
    if not checksum_path.exists():
        failures.append("originals_backup/SHA256SUMS.txt is missing")
    else:
        try:
            expected = read_checksum_manifest(checksum_path)
            actual = {path.name: sha256_file(path) for path in backup_images_found}
            if expected != actual:
                failures.append("backup checksum manifest does not match backup contents")
        except ValueError as error:
            failures.append(str(error))

    duplicate_backups = find_duplicate_hashes(backup_images_found)
    if duplicate_backups:
        failures.append(f"backup contains {len(duplicate_backups)} duplicate image hash group(s)")

    curated_images: list[Path] = []
    for directory_name in CURATED_DIR_NAMES:
        curated_images.extend(image_files(problem_dir / directory_name, recursive=True))
    if not image_files(problem_dir / "question_description", recursive=True):
        failures.append("question_description contains no images")

    duplicate_curated = find_duplicate_hashes(curated_images)
    if duplicate_curated:
        failures.append(f"curated set contains {len(duplicate_curated)} duplicate image hash group(s)")

    loose_images = image_files(problem_dir)
    if loose_images:
        failures.append(f"problem root contains {len(loose_images)} loose image(s)")

    if not (problem_dir / "README.md").exists():
        failures.append("README.md is missing")
    if has_level_suffix(problem_dir.name):
        failures.append("problem directory still uses a temporary level suffix")

    level_named_solutions = [
        path.name
        for path in problem_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".py", ".go", ".java", ".ts", ".js", ".cpp"} and "level_" in path.stem.lower()
    ]
    if level_named_solutions:
        failures.append(f"solution filenames still contain level suffixes: {', '.join(level_named_solutions)}")

    if failures:
        print("audit: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("audit: PASS")
    print(f"- backups: {len(backup_images_found)} unique images with matching checksums")
    print(f"- curated: {len(curated_images)} unique images")
    print("- root: no loose images")
    print("- naming: stable problem and solution names")
    print("- guide: README.md present")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup", help="copy and verify unique source images")
    backup_parser.add_argument("problem_dir", type=Path)
    backup_parser.add_argument("--input-dir", action="append", default=[], type=Path)

    audit_parser = subparsers.add_parser("audit", help="validate a cleaned problem package")
    audit_parser.add_argument("problem_dir", type=Path)
    return parser


def main() -> int:
    """Dispatch backup or audit without mutating anything outside the target folder."""
    args = build_parser().parse_args()
    problem_dir = args.problem_dir.expanduser().resolve()
    if args.command == "backup":
        input_dirs = [path.expanduser().resolve() for path in args.input_dir]
        return backup_images(problem_dir, input_dirs)
    return audit_problem(problem_dir)


if __name__ == "__main__":
    sys.exit(main())
