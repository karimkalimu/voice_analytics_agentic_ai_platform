import argparse
import csv
import json
import os
import platform
import signal
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psutil


def find_process(kind: str) -> psutil.Process:
    matches = []

    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (process.info["name"] or "").lower()
            cmdline = " ".join(process.info["cmdline"] or []).lower()

            if kind == "api":
                if "uvicorn" in name or "uvicorn app.main:app" in cmdline:
                    matches.append(process)

            elif kind == "tusd":
                if name == "tusd" or "/tusd " in cmdline or cmdline.endswith("/tusd"):
                    matches.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not matches:
        raise RuntimeError(f"Could not find running {kind} process")

    if len(matches) > 1:
        values = ", ".join(str(p.pid) for p in matches)
        raise RuntimeError(
            f"Multiple {kind} processes found: {values}. Pass --{kind}-pid explicitly."
        )

    return matches[0]


def get_process(pid: int | None, kind: str) -> psutil.Process:
    if pid is not None:
        try:
            process = psutil.Process(pid)
        except psutil.NoSuchProcess as exc:
            raise RuntimeError(f"{kind} PID {pid} does not exist") from exc
        return process

    return find_process(kind)


def process_tree(root: psutil.Process) -> list[psutil.Process]:
    processes = []

    try:
        if root.is_running():
            processes.append(root)
            processes.extend(root.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    unique = {}
    for process in processes:
        unique[process.pid] = process

    return list(unique.values())


def prime_cpu(processes: list[psutil.Process], known: set[int]) -> None:
    for process in processes:
        if process.pid in known:
            continue

        try:
            process.cpu_percent(interval=None)
            known.add(process.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def measure(root: psutil.Process, known: set[int]) -> dict:
    processes = process_tree(root)
    prime_cpu(processes, known)

    cpu = 0.0
    rss = 0
    alive = 0

    for process in processes:
        try:
            cpu += process.cpu_percent(interval=None)
            rss += process.memory_info().rss
            alive += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return {
        "parent_pid": root.pid,
        "cpu_percent": cpu,
        "rss_mb": rss / (1024 * 1024),
        "child_count": max(0, alive - 1),
    }


def cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as file:
            for line in file:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass

    return platform.processor() or "unknown"


def ubuntu_version() -> str:
    try:
        result = subprocess.run(
            ["lsb_release", "-ds"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip().strip('"')
    except Exception:
        return platform.platform()


def command_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
        )

        output = result.stdout.strip() or result.stderr.strip()
        return output.splitlines()[0] if output else None
    except Exception:
        return None


def machine_metadata(api: psutil.Process, tusd: psutil.Process) -> dict:
    memory = psutil.virtual_memory()

    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "os": ubuntu_version(),
        "machine": platform.machine(),
        "cpu_model": cpu_model(),
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "total_ram_mb": round(memory.total / (1024 * 1024), 2),
        "python_version": platform.python_version(),
        "tusd_version": command_version([".tools/tusd", "-version"])
        or command_version(["tusd", "-version"]),
        "api_pid": api.pid,
        "tusd_pid": tusd.pid,
        "api_cmdline": api.cmdline(),
        "tusd_cmdline": tusd.cmdline(),
    }


def update_stats(stats: dict, service: str, cpu: float, rss: float) -> None:
    entry = stats[service]
    entry["samples"] += 1
    entry["cpu_sum"] += cpu
    entry["rss_sum"] += rss
    entry["peak_cpu"] = max(entry["peak_cpu"], cpu)
    entry["peak_rss"] = max(entry["peak_rss"], rss)


def summarize(stats: dict, duration: float) -> dict:
    output = {"duration_sec": round(duration, 2), "services": {}}

    for service, entry in stats.items():
        count = entry["samples"]

        output["services"][service] = {
            "samples": count,
            "avg_cpu_percent": round(entry["cpu_sum"] / count, 2) if count else 0,
            "peak_cpu_percent": round(entry["peak_cpu"], 2),
            "avg_rss_mb": round(entry["rss_sum"] / count, 2) if count else 0,
            "peak_rss_mb": round(entry["peak_rss"], 2),
        }

    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-pid", type=int)
    parser.add_argument("--tusd-pid", type=int)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--output-dir", default="metrics")
    args = parser.parse_args()

    if args.interval <= 0:
        raise SystemExit("--interval must be greater than zero")

    api = get_process(args.api_pid, "api")
    tusd = get_process(args.tusd_pid, "tusd")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"resources_{run_name}.csv"
    metadata_path = output_dir / f"resources_{run_name}_metadata.json"
    summary_path = output_dir / f"resources_{run_name}_summary.json"

    metadata = machine_metadata(api, tusd)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"API PID:  {api.pid}")
    print(f"tusd PID: {tusd.pid}")
    print(f"CSV:      {csv_path}")
    print("Press Ctrl+C to stop.")

    known_api: set[int] = set()
    known_tusd: set[int] = set()

    prime_cpu(process_tree(api), known_api)
    prime_cpu(process_tree(tusd), known_tusd)

    stats = defaultdict(
        lambda: {
            "samples": 0,
            "cpu_sum": 0.0,
            "rss_sum": 0.0,
            "peak_cpu": 0.0,
            "peak_rss": 0.0,
        }
    )

    started = time.monotonic()

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "timestamp",
                "elapsed_sec",
                "service",
                "parent_pid",
                "cpu_percent",
                "rss_mb",
                "child_count",
            ],
        )
        writer.writeheader()

        try:
            while True:
                time.sleep(args.interval)

                if not api.is_running():
                    raise RuntimeError("API process stopped")

                if not tusd.is_running():
                    raise RuntimeError("tusd process stopped")

                timestamp = datetime.now(timezone.utc).isoformat()
                elapsed = time.monotonic() - started

                api_result = measure(api, known_api)
                tusd_result = measure(tusd, known_tusd)

                combined = {
                    "parent_pid": "",
                    "cpu_percent": api_result["cpu_percent"]
                    + tusd_result["cpu_percent"],
                    "rss_mb": api_result["rss_mb"] + tusd_result["rss_mb"],
                    "child_count": api_result["child_count"]
                    + tusd_result["child_count"],
                }

                for service, result in (
                    ("api", api_result),
                    ("tusd", tusd_result),
                    ("combined", combined),
                ):
                    writer.writerow(
                        {
                            "timestamp": timestamp,
                            "elapsed_sec": round(elapsed, 3),
                            "service": service,
                            "parent_pid": result["parent_pid"],
                            "cpu_percent": round(result["cpu_percent"], 2),
                            "rss_mb": round(result["rss_mb"], 2),
                            "child_count": result["child_count"],
                        }
                    )

                    update_stats(
                        stats,
                        service,
                        result["cpu_percent"],
                        result["rss_mb"],
                    )

                file.flush()

        except KeyboardInterrupt:
            pass

    duration = time.monotonic() - started
    final_summary = summarize(stats, duration)

    summary_path.write_text(
        json.dumps(final_summary, indent=2),
        encoding="utf-8",
    )

    print()
    print(json.dumps(final_summary, indent=2))
    print()
    print(f"CSV:      {csv_path}")
    print(f"Metadata: {metadata_path}")
    print(f"Summary:  {summary_path}")


if __name__ == "__main__":
    main()
