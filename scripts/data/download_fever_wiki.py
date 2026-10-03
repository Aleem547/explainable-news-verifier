import argparse
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DIRECTORY = PROJECT_ROOT / "data" / "raw" / "fever"
METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

WIKI_URL = "https://fever.ai/download/fever/wiki-pages.zip"

WIKI_ARCHIVE = RAW_DIRECTORY / "wiki-pages.zip"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_wiki_download_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        for chunk in iter(
            lambda: file_handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def validate_zip(path: Path) -> int:
    if not zipfile.is_zipfile(path):
        raise ValueError(f"Downloaded file is not a valid ZIP archive: {path}")

    with zipfile.ZipFile(path) as archive:
        bad_file = archive.testzip()

        if bad_file is not None:
            raise ValueError(f"Corrupted file found inside ZIP: {bad_file}")

        jsonl_members = [name for name in archive.namelist() if name.lower().endswith(".jsonl")]

    if not jsonl_members:
        raise ValueError("No JSONL Wikipedia files were found in the archive.")

    return len(jsonl_members)


def download_archive(
    force: bool,
) -> None:
    RAW_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    if WIKI_ARCHIVE.exists() and not force:
        print(f"Using existing archive: {WIKI_ARCHIVE}")
        return

    temporary_path = WIKI_ARCHIVE.with_suffix(".zip.download")

    if temporary_path.exists():
        temporary_path.unlink()

    print("Downloading FEVER Wikipedia corpus...")
    print(f"Source: {WIKI_URL}")
    print()

    timeout = httpx.Timeout(
        connect=30.0,
        read=None,
        write=30.0,
        pool=30.0,
    )

    downloaded_bytes = 0
    last_reported_mb = 0

    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Explainable-News-Verifier/0.1"},
    ) as client:
        with client.stream(
            "GET",
            WIKI_URL,
        ) as response:
            response.raise_for_status()

            with temporary_path.open("wb") as output_file:
                for chunk in response.iter_bytes():
                    output_file.write(chunk)

                    downloaded_bytes += len(chunk)

                    downloaded_mb = downloaded_bytes // (1024 * 1024)

                    if downloaded_mb - last_reported_mb >= 100:
                        print(f"Downloaded: {downloaded_mb} MB")

                        last_reported_mb = downloaded_mb

    temporary_path.replace(WIKI_ARCHIVE)

    print()
    print(f"Saved: {WIKI_ARCHIVE}")


def write_manifest() -> None:
    print("Validating ZIP archive...")

    jsonl_file_count = validate_zip(WIKI_ARCHIVE)

    manifest = {
        "dataset": "fever",
        "artifact": "wikipedia_corpus",
        "source_url": WIKI_URL,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "filename": WIKI_ARCHIVE.name,
        "size_bytes": WIKI_ARCHIVE.stat().st_size,
        "sha256": sha256_file(WIKI_ARCHIVE),
        "jsonl_file_count": jsonl_file_count,
    }

    MANIFEST_PATH.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print("Archive validation successful.")
    print(f"JSONL files found: {jsonl_file_count}")

    print(f"Manifest: {MANIFEST_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("Download the official FEVER pre-processed Wikipedia corpus.")
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Download the archive again.",
    )

    args = parser.parse_args()

    download_archive(
        force=args.force,
    )

    write_manifest()

    print()
    print("FEVER Wikipedia download completed.")


if __name__ == "__main__":
    main()
