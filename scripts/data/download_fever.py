import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DIRECTORY = PROJECT_ROOT / "data" / "raw" / "fever"
METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

FEVER_FILES = {
    "train": (
        "train.jsonl",
        "https://fever.ai/download/fever/train.jsonl",
    ),
    "validation": (
        "paper_dev.jsonl",
        "https://fever.ai/download/fever/paper_dev.jsonl",
    ),
    "test": (
        "paper_test.jsonl",
        "https://fever.ai/download/fever/paper_test.jsonl",
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def download_file(
    client: httpx.Client,
    url: str,
    destination: Path,
    force: bool,
) -> None:
    if destination.exists() and not force:
        print(f"Skipping existing file: {destination.name}")
        return

    temporary_path = destination.with_suffix(destination.suffix + ".download")

    print(f"Downloading: {destination.name}")

    with client.stream("GET", url) as response:
        response.raise_for_status()

        with temporary_path.open("wb") as output_file:
            for chunk in response.iter_bytes():
                output_file.write(chunk)

    temporary_path.replace(destination)

    print(f"Saved: {destination}")


def build_manifest() -> dict[str, object]:
    files: dict[str, object] = {}

    for split, (filename, url) in FEVER_FILES.items():
        path = RAW_DIRECTORY / filename

        files[split] = {
            "filename": filename,
            "source_url": url,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    return {
        "dataset": "fever",
        "downloaded_at": datetime.now(UTC).isoformat(),
        "files": files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the official FEVER dataset.")

    parser.add_argument(
        "--force",
        action="store_true",
        help="Download files again even if they already exist.",
    )

    args = parser.parse_args()

    RAW_DIRECTORY.mkdir(parents=True, exist_ok=True)
    METADATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    timeout = httpx.Timeout(
        connect=30.0,
        read=300.0,
        write=30.0,
        pool=30.0,
    )

    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Explainable-News-Verifier/0.1"},
    ) as client:
        for filename, url in FEVER_FILES.values():
            download_file(
                client=client,
                url=url,
                destination=RAW_DIRECTORY / filename,
                force=args.force,
            )

    manifest = build_manifest()

    manifest_path = METADATA_DIRECTORY / "fever_download_manifest.json"

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print()
    print("FEVER download completed.")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
