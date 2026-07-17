#!/usr/bin/env python3
"""Validate and create the versioned AceHLS easy-deploy archive."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
EASY_DEPLOY_DIR = ROOT / "easy-deploy"
VERSION_FILE = ROOT / "src/app/version.txt"
VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+(?:-[a-z0-9][a-z0-9.-]*)?$")
PACKAGE_FILES = (
    Path("README.md"),
    Path("orchestrator-local/compose.yml"),
    Path("orchestrator-local/.env.example"),
    Path("orchestrator-remote/compose.yml"),
    Path("orchestrator-remote/.env.example"),
)
PLACEHOLDER_TOKEN = "cambia-este-token-compartido"
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def read_version() -> str:
    """Read and validate the application version."""
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Versión no válida en {VERSION_FILE}: {version!r}")
    return version


def validate_sources(version: str) -> None:
    """Reject incomplete, build-based, unversioned or secret-bearing bundles."""
    missing = [path for path in PACKAGE_FILES if not (EASY_DEPLOY_DIR / path).is_file()]
    if missing:
        raise ValueError(f"Faltan archivos easy-deploy: {', '.join(map(str, missing))}")
    if any(path.name == ".env" for path in EASY_DEPLOY_DIR.rglob(".env")):
        raise ValueError("easy-deploy no puede contener archivos .env reales")

    image = f"tscneo/ace-hls-viewer:{version.removeprefix('v')}"
    for relative_path in PACKAGE_FILES:
        text = (EASY_DEPLOY_DIR / relative_path).read_text(encoding="utf-8")
        if relative_path.name == "compose.yml":
            if re.search(r"^\s*build\s*:", text, re.MULTILINE):
                raise ValueError(f"{relative_path} contiene build")
            if image not in text:
                raise ValueError(f"{relative_path} no usa la imagen {image}")
        if relative_path.name == ".env.example":
            if f"ACE_HLS_IMAGE={image}" not in text:
                raise ValueError(f"{relative_path} no fija ACE_HLS_IMAGE={image}")
            token_match = re.search(r"^ORCHESTRATOR_API_TOKEN=(.*)$", text, re.MULTILINE)
            if token_match is None or token_match.group(1) != PLACEHOLDER_TOKEN:
                raise ValueError(f"{relative_path} debe contener solo el token de ejemplo")


def _zip_info(archive_path: str) -> ZipInfo:
    """Create deterministic metadata for one archived file."""
    info = ZipInfo(archive_path, date_time=ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def create_archive(output_dir: Path) -> Path:
    """Create and return a deterministic archive for the current version."""
    version = read_version()
    validate_sources(version)
    package_name = f"ace-hls-easy-deploy-{version}"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"{package_name}.zip"

    with ZipFile(archive_path, "w") as archive:
        for relative_path in sorted(PACKAGE_FILES, key=str):
            source = EASY_DEPLOY_DIR / relative_path
            archive_name = f"{package_name}/{relative_path.as_posix()}"
            archive.writestr(_zip_info(archive_name), source.read_bytes())
        archive.writestr(_zip_info(f"{package_name}/VERSION"), f"{version}\n".encode())

    return archive_path


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist",
        help="Directorio de salida (predeterminado: dist/)",
    )
    return parser.parse_args()


def main() -> int:
    """Validate sources and print the generated archive path."""
    args = parse_args()
    archive_path = create_archive(args.output_dir.resolve())
    print(archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
