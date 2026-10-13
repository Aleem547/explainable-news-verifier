#!/usr/bin/env python3
"""Phase 11C read-only benchmark monitor for the local Explainable News Verifier.

Run from the repository root while submitting claims through the authenticated web UI.
Requires only Python 3.12+ and the installed Docker CLI/Compose plugin.

This tool never sends requests to the verification API, never bypasses authentication,
and never reads or includes the text of submitted claims.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

COMPOSE = ["docker", "compose", "--env-file", ".env", "-f", "infra/docker/compose.dev.yml"]
LATENCY_RE = re.compile(r"\blatency_ms=([0-9]+(?:\.[0-9]+)?)\b")
HTTP_RE = re.compile(r'"POST /api/v1/verify HTTP/[^\"]+"\s+(\d{3})\b')
AUDIT_STATUS_RE = re.compile(r"\bstatus_code=(\d{3})\b")
UNITS = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def command(args: list[str], timeout: int = 30) -> str:
    process = subprocess.run(
        args, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if process.returncode != 0:
        # Truncate errors: Docker's CLI can return long, noisy diagnostic output.
        raise RuntimeError(f"Command failed ({process.returncode}): {args[0:2]}: "
                           f"{process.stderr.strip()[-700:]}")
    return process.stdout


def number_to_bytes(raw: str) -> float:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)\s*", raw)
    if not match:
        raise ValueError(f"Unrecognized Docker memory value: {raw!r}")
    unit = match.group(2).upper()
    if unit not in UNITS:
        raise ValueError(f"Unrecognized Docker memory unit: {unit!r}")
    return float(match.group(1)) * UNITS[unit]


def parse_stats_line(line: str, timestamp: datetime) -> dict[str, object]:
    info = json.loads(line)
    mem_parts = info["MemUsage"].split("/")
    if len(mem_parts) != 2:
        raise ValueError("Docker stats did not return memory usage and limit")
    memory = number_to_bytes(mem_parts[0]) / (1024**2)
    limit = number_to_bytes(mem_parts[1]) / (1024**2)
    return {
        "timestamp_utc": utc_stamp(timestamp),
        "cpu_percent": float(info["CPUPerc"].strip().rstrip("%")),
        "memory_mib": round(memory, 3),
        "memory_limit_mib": round(limit, 3),
        "pids": int(info["PIDs"]),
    }


def percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    # Nearest-rank percentile, clearly stated in the report.
    import math
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percent / 100) - 1))
    return round(ordered[index], 3)


def parse_logs(logs: str) -> dict[str, object]:
    latencies: list[float] = []
    http_status_counts: dict[str, int] = {}
    audit_status_counts: dict[str, int] = {}
    queue_events: dict[str, int] = {}
    for line in logs.splitlines():
        if "verification_completed" in line:
            match = LATENCY_RE.search(line)
            if match:
                latencies.append(round(float(match.group(1)) / 1000, 6))
        match = HTTP_RE.search(line)
        if match:
            code = match.group(1)
            http_status_counts[code] = http_status_counts.get(code, 0) + 1
        if "verification_request_audit" in line:
            match = AUDIT_STATUS_RE.search(line)
            if match:
                code = match.group(1)
                audit_status_counts[code] = audit_status_counts.get(code, 0) + 1
        for event in (
            "verification_queue_admitted", "verification_queue_full",
            "verification_queue_timeout", "verification_waiter_cancelled",
            "verification_failed", "verification_busy",
        ):
            if event in line:
                queue_events[event] = queue_events.get(event, 0) + 1
    return {
        "completed_latency_seconds": latencies,
        "http_status_counts": http_status_counts,
        "audit_status_counts": audit_status_counts,
        "queue_event_counts": queue_events,
    }


def summarize(samples: list[dict[str, object]], events: dict[str, object],
              start: datetime, end: datetime, service: str, interval: float,
              sampling_failures: int) -> dict[str, object]:
    latencies = events["completed_latency_seconds"]
    assert isinstance(latencies, list)
    cpus = [float(s["cpu_percent"]) for s in samples]
    memories = [float(s["memory_mib"]) for s in samples]
    pids = [int(s["pids"]) for s in samples]
    window = max((end - start).total_seconds(), 0.001)
    return {
        "schema_version": 1,
        "phase": "11C.3",
        "scenario": "authenticated browser verification; read-only Docker sampling",
        "start_utc": utc_stamp(start),
        "end_utc": utc_stamp(end),
        "elapsed_seconds": round(window, 2),
        "docker_service": service,
        "requested_sample_interval_seconds": interval,
        "sample_count": len(samples),
        "sample_failures": sampling_failures,
        "latency_seconds": {
            "count": len(latencies),
            "values": latencies,
            "mean": round(statistics.mean(latencies), 3) if latencies else None,
            "min": round(min(latencies), 3) if latencies else None,
            "max": round(max(latencies), 3) if latencies else None,
            "p50": percentile(latencies, 50),
            "p90": percentile(latencies, 90),
            "p95": percentile(latencies, 95),
            "percentile_method": "nearest_rank",
        },
        "docker_resource_samples": {
            "mean_cpu_percent": round(statistics.mean(cpus), 2) if cpus else None,
            "max_cpu_percent": round(max(cpus), 2) if cpus else None,
            "mean_memory_mib": round(statistics.mean(memories), 2) if memories else None,
            "max_memory_mib": round(max(memories), 2) if memories else None,
            "max_pids": max(pids) if pids else None,
            "last_observed_memory_limit_mib": samples[-1]["memory_limit_mib"] if samples else None,
        },
        "request_http_status_counts": events["http_status_counts"],
        "request_audit_status_counts": events["audit_status_counts"],
        "queue_event_counts": events["queue_event_counts"],
        "notes": [
            "Manual browser submissions do not measure sustainable maximum throughput.",
            "API verification_completed latency is backend inference latency, not browser end-to-end time.",
            "CPU and memory maxima are peaks among snapshots, not guaranteed process maxima.",
            "Small-sample percentiles (especially p95) are not reliable capacity estimates.",
            "HTTP and audit statuses are independent views of requests; do not add their counts.",
            "Docker CPU percentages may exceed 100% for multi-core workloads.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=120,
                        help="Capture window in seconds (default 120)")
    parser.add_argument("--interval", type=float, default=2,
                        help="Approximate interval between samples in seconds (default 2)")
    parser.add_argument("--output-dir", default="benchmarks/results",
                        help="Where to save JSON and CSV reports")
    args = parser.parse_args()
    if not 15 <= args.duration <= 3600 or not 1 <= args.interval <= 60:
        parser.error("--duration must be 15-3600 seconds and --interval must be 1-60 seconds")
    root = Path.cwd()
    if not (root / "infra/docker/compose.dev.yml").is_file() or not (root / ".env").is_file():
        parser.error("Run from the project root containing .env and infra/docker/compose.dev.yml")

    try:
        container_id = command(COMPOSE + ["ps", "-q", "api"]).strip()
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        print(f"Docker Compose unavailable: {exc}", file=sys.stderr)
        return 1
    if not container_id:
        print("API container is not running; start it before benchmarking.", file=sys.stderr)
        return 1

    start = utc_now()
    run_id = start.strftime("%Y%m%dT%H%M%SZ")
    print(f"Capturing API resource metrics for {args.duration}s starting {utc_stamp(start)}")
    print("Submit verification claims in the website now. Press Ctrl+C to stop early.")
    deadline = time.monotonic() + args.duration
    samples: list[dict[str, object]] = []
    failures = 0
    try:
        while time.monotonic() < deadline:
            try:
                output = command(
                    ["docker", "stats", "--no-stream", "--format", "{{json .}}", container_id],
                    timeout=30,
                )
                lines = [line for line in output.splitlines() if line.strip()]
                if not lines:
                    raise ValueError("Empty docker stats response")
                samples.append(parse_stats_line(lines[0], utc_now()))
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
                    subprocess.TimeoutExpired, RuntimeError) as exc:
                failures += 1
                print(f"Resource sample warning: {exc}", file=sys.stderr)
            time.sleep(min(args.interval, max(0.0, deadline - time.monotonic())))
    except KeyboardInterrupt:
        print("\nCapture interrupted; writing partial report.")
    end = utc_now()

    log_error = None
    try:
        logs = command(COMPOSE + ["logs", "--since", utc_stamp(start),
                                  "--until", utc_stamp(end), "--no-color", "api"],
                       timeout=45)
        events = parse_logs(logs)
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        log_error = str(exc)
        print(f"Cannot collect API logs: {exc}", file=sys.stderr)
        events = parse_logs("")

    report = summarize(samples, events, start, end, "api", args.interval, failures)
    if log_error:
        report["log_collection_error"] = log_error
    directory = root / args.output_dir
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"phase11c_capture_{run_id}.json"
    samples_path = directory / f"phase11c_capture_{run_id}_samples.csv"
    latencies_path = directory / f"phase11c_capture_{run_id}_latencies.csv"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with samples_path.open("w", newline="", encoding="utf-8") as csv_file:
        columns = ["timestamp_utc", "cpu_percent", "memory_mib", "memory_limit_mib", "pids"]
        writer = csv.DictWriter(csv_file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(samples)
    with latencies_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["completion_number", "latency_seconds"])
        for index, latency in enumerate(events["completed_latency_seconds"], start=1):
            writer.writerow([index, latency])

    latency_summary = report["latency_seconds"]
    resources = report["docker_resource_samples"]
    print(f"\nSaved JSON: {json_path}")
    print(f"Saved resource CSV: {samples_path}")
    print(f"Saved latency CSV: {latencies_path}")
    print(f"Requests completed: {latency_summary['count']}")
    print(f"Mean latency: {latency_summary['mean']}s; p50: {latency_summary['p50']}s; "
          f"p95: {latency_summary['p95']}s")
    print(f"Observed peak CPU: {resources['max_cpu_percent']}%; "
          f"observed peak RAM: {resources['max_memory_mib']} MiB; "
          f"maximum PIDs: {resources['max_pids']}")
    print(f"Request HTTP statuses: {report['request_http_status_counts']}")
    if log_error or not samples:
        print("Warning: data collection was incomplete; see the JSON report.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
