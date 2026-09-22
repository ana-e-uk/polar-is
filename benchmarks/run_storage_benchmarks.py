"""Compare the legacy block store with the redesigned product store."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
from typing import Any


VARIABLE = "sea_surface_temperature"
SMALL_REGION = {"west": 3.756, "east": 6.921, "south": 66.97, "north": 67.847}
BROAD_REGION = {"west": -20, "east": 90, "south": 55, "north": 90}


def _query(
    *,
    region: dict[str, float],
    start: str,
    end: str,
    time_unit: str,
    function: str,
    factor: int = 1,
    repository: str | None = None,
    dataset: str | None = None,
) -> dict[str, Any]:
    return {
        "repository": repository,
        "dataset": dataset,
        "variable": VARIABLE,
        "region": region,
        "time_start": start,
        "time_end": end,
        "coarseness_factor": factor,
        "time_unit": time_unit,
        "function": function,
        "aggregation_method": "mean",
        "additional_parameters": {},
    }


SCENARIOS = (
    {
        "id": "era5_source_timeseries",
        "name": "ERA5 Source (1H) timeseries, small, 2 days",
        "old": _query(region=SMALL_REGION, start="2018-01-01", end="2018-01-02",
                      time_unit="Hour", function="timeseries",
                      repository="copernicusclimatedatastore", dataset="era5_single_level"),
        "redesigned": _query(region=SMALL_REGION, start="2018-01-01", end="2018-01-02",
                             time_unit="Source", function="timeseries",
                             repository="copernicusclimatedatastore", dataset="era5_single_level"),
    },
    {
        "id": "emsst_source_timeseries",
        "name": "EMSST Source (1D) timeseries, small, 2 days",
        "old": _query(region=SMALL_REGION, start="2018-01-01", end="2018-01-02",
                      time_unit="Day", function="timeseries",
                      repository="noaancei", dataset="emsst"),
        "redesigned": _query(region=SMALL_REGION, start="2018-01-01", end="2018-01-02",
                             time_unit="Source", function="timeseries",
                             repository="noaancei", dataset="emsst"),
    },
    {
        "id": "multi_day_heatmap_small",
        "name": "Multi-dataset Day heatmap, small",
        "old": _query(region=SMALL_REGION, start="2018-01-01", end="2018-01-05",
                      time_unit="Day", function="heatmap"),
        "redesigned": _query(region=SMALL_REGION, start="2018-01-01", end="2018-01-05",
                             time_unit="Day", function="heatmap"),
    },
    {
        "id": "multi_day_heatmap_broad",
        "name": "Multi-dataset Day heatmap, broad",
        "old": _query(region=BROAD_REGION, start="2018-01-01", end="2018-01-05",
                      time_unit="Day", function="heatmap"),
        "redesigned": _query(region=BROAD_REGION, start="2018-01-01", end="2018-01-05",
                             time_unit="Day", function="heatmap"),
    },
    {
        "id": "month_coarsen_2_heatmap",
        "name": "Month, coarsen-2 heatmap, broad",
        "old": _query(region=BROAD_REGION, start="2018-01-01", end="2018-01-31",
                      time_unit="Month", function="heatmap", factor=2),
        "redesigned": _query(region=BROAD_REGION, start="2018-01-01", end="2018-01-31",
                             time_unit="Month", function="heatmap", factor=2),
    },
)


class Worker:
    def __init__(self, version: str, repository: Path, scratch: Path):
        self.version = version
        self.repository = repository
        self.stderr_path = scratch / f"{version}.stderr"
        self.memory_path = scratch / f"{version}.time"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(repository)
        environment["POLARIS_ACCESS_MODE"] = "anonymous"
        command = [
            "/usr/bin/time", "-l", "-o", str(self.memory_path),
            str(repository / ".venv" / "bin" / "python"), "-u",
            str(Path(__file__).with_name("storage_benchmark_worker.py")),
        ]
        self.stderr = self.stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            command,
            cwd=repository,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            text=True,
            bufsize=1,
        )

    def request(self, mode: str, query: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(json.dumps({
            "mode": mode,
            "query": query,
            "output_dir": str(output_dir),
        }) + "\n")
        self.process.stdin.flush()
        response_line = self.process.stdout.readline()
        if not response_line:
            self.close()
            error = self.stderr_path.read_text(encoding="utf-8")
            raise RuntimeError(f"{self.version} worker exited unexpectedly:\n{error}")
        response = json.loads(response_line)
        if not response["ok"]:
            raise RuntimeError(f"{self.version}: {response['error']}")
        return response["result"]

    def close(self) -> int:
        if self.process.poll() is None and self.process.stdin is not None:
            self.process.stdin.write(json.dumps({"mode": "stop"}) + "\n")
            self.process.stdin.flush()
        return_code = self.process.wait()
        self.stderr.close()
        return return_code

    def peak_memory_bytes(self) -> int | None:
        text = self.memory_path.read_text(encoding="utf-8")
        match = re.search(r"(\d+)\s+maximum resident set size", text)
        return int(match.group(1)) if match else None


def _tree_metrics(repository: Path, version: str) -> dict[str, Any]:
    data = repository / "storage" / "data"
    if version == "old":
        managed_roots = [data / "containers", data / "container_definitions"]
        products = list((data / "containers").rglob("*.nc"))
        grids: list[Path] = []
        lookups: list[Path] = []
        metadata = list((data / "containers").glob("*/metadata.jsonl"))
    else:
        managed_roots = [data / "products", data / "catalogs", data / "bucket_lookup"]
        products = list((data / "products").rglob("*.nc"))
        grids = list((data / "catalogs" / "grids").glob("*.nc"))
        lookups = list((data / "bucket_lookup").glob("*.jsonl"))
        metadata = [data / "metadata.jsonl", data / "catalogs" / "grids.jsonl",
                    data / "catalogs" / "datasets.jsonl"]

    def files_under(roots):
        return [path for root in roots if root.exists() for path in root.rglob("*") if path.is_file()]

    managed_files = files_under(managed_roots)
    all_files = [path for path in data.rglob("*") if path.is_file()]
    return {
        "managed_bytes": sum(path.stat().st_size for path in managed_files),
        "total_data_bytes": sum(path.stat().st_size for path in all_files),
        "managed_files": len(managed_files),
        "product_files": len(products),
        "grid_files": len(grids),
        "lookup_files": len(lookups),
        "metadata_files": len([path for path in metadata if path.is_file()]),
        "metadata_records": sum(
            len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
            for path in metadata if path.is_file()
        ),
    }


def _format_seconds(value: float) -> str:
    return f"{value:.3f}"


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "n/a"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    raise AssertionError("unreachable")


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Polar-is storage benchmark",
        "",
        f"Run: {payload['created_at']}",
        "",
        "Times are backend-only wall times. Each scenario/version used one persistent, newly started process: first query = cold-ish, second = untimed warm-up, followed by three measured warm queries. Old and redesigned calls were alternated. Peak RSS covers that scenario process, including its API check.",
        "",
        "| Scenario | Old cold-ish | New cold-ish | Old warm median | New warm median | Warm speedup | Old plan | New plan | Old execute/write | New execute/write | Old peak RSS | New peak RSS |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario in payload["scenarios"]:
        old = scenario["old"]
        new = scenario["redesigned"]
        speedup = old["warm_median_seconds"] / new["warm_median_seconds"]
        lines.append(
            f"| {scenario['name']} | {_format_seconds(old['cold']['total_seconds'])} s | "
            f"{_format_seconds(new['cold']['total_seconds'])} s | "
            f"{_format_seconds(old['warm_median_seconds'])} s | "
            f"{_format_seconds(new['warm_median_seconds'])} s | {speedup:.2f}× | "
            f"{_format_seconds(old['warm_plan_median_seconds'])} s | "
            f"{_format_seconds(new['warm_plan_median_seconds'])} s | "
            f"{_format_seconds(old['warm_execution_median_seconds'])} s | "
            f"{_format_seconds(new['warm_execution_median_seconds'])} s | "
            f"{_format_bytes(old['peak_memory_bytes'])} | {_format_bytes(new['peak_memory_bytes'])} |"
        )
    lines.extend([
        "",
        "## Correctness and output",
        "",
        "| Scenario | Version | Groups | Timestamps | Spatial cells | Valid values | Result size | Datasets | API end-to-end |",
        "|---|---|---:|---:|---:|---:|---:|---|---:|",
    ])
    for scenario in payload["scenarios"]:
        for version in ("old", "redesigned"):
            result = scenario[version]
            metrics = result["warm_runs"][-1]
            lines.append(
                f"| {scenario['name']} | {version} | {metrics['groups']} | "
                f"{metrics['timestamps']} | {metrics['spatial_cells']} | "
                f"{metrics['valid_values']} | {_format_bytes(metrics['result_bytes'])} | "
                f"{', '.join(metrics['datasets'])} | "
                f"{_format_seconds(result['api']['total_seconds'])} s "
                f"({result['api']['status']}) |"
            )
    lines.extend([
        "",
        "## Storage inventory",
        "",
        "| Version | Managed size | Total data directory | Managed files | Product files | Grid files | Lookup files | Metadata files | Metadata records |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for version in ("old", "redesigned"):
        item = payload["storage"][version]
        lines.append(
            f"| {version} | {_format_bytes(item['managed_bytes'])} | "
            f"{_format_bytes(item['total_data_bytes'])} | {item['managed_files']} | "
            f"{item['product_files']} | {item['grid_files']} | {item['lookup_files']} | "
            f"{item['metadata_files']} | {item['metadata_records']} |"
        )
    lines.extend([
        "",
        "## Interpretation notes",
        "",
        "- ERA5 native hourly is queried as `Hour` in old storage and `Source` in redesigned storage.",
        "- EMSST native daily is queried as `Day` in old storage and `Source` in redesigned storage.",
        "- Literal multi-dataset `Day` queries can have different group counts: old treats native daily as Day, while redesigned uses Day only for a product derived from finer source cadence.",
        "- Managed size excludes downloads, standardized inputs, query outputs, caches, and backups. Total data-directory size includes them.",
        "- Cold-ish measurements use a newly started Python process but do not clear the macOS filesystem cache.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def run(old_root: Path, redesigned_root: Path, output: Path) -> dict[str, Any]:
    repositories = {"old": old_root.resolve(), "redesigned": redesigned_root.resolve()}
    payload: dict[str, Any] = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "repositories": {key: str(value) for key, value in repositories.items()},
        "storage": {key: _tree_metrics(value, key) for key, value in repositories.items()},
        "scenarios": [],
    }
    scratch_root = Path(tempfile.mkdtemp(prefix="polaris-storage-benchmark-"))
    try:
        for scenario_index, scenario in enumerate(SCENARIOS):
            scenario_scratch = scratch_root / scenario["id"]
            scenario_scratch.mkdir(parents=True)
            workers = {
                version: Worker(version, repository, scenario_scratch)
                for version, repository in repositories.items()
            }
            order = ("old", "redesigned") if scenario_index % 2 == 0 else ("redesigned", "old")
            results = {
                version: {"cold": None, "warm_runs": [], "api": None}
                for version in repositories
            }
            try:
                for version in order:
                    results[version]["cold"] = workers[version].request(
                        "direct", scenario[version], scenario_scratch / version / "direct"
                    )
                for version in order:
                    workers[version].request(
                        "direct", scenario[version], scenario_scratch / version / "direct"
                    )
                for _ in range(3):
                    for version in order:
                        results[version]["warm_runs"].append(workers[version].request(
                            "direct", scenario[version], scenario_scratch / version / "direct"
                        ))
                for version in order:
                    results[version]["api"] = workers[version].request(
                        "api", scenario[version], scenario_scratch / version / "api"
                    )
            finally:
                exit_failures = []
                for version, worker in workers.items():
                    return_code = worker.close()
                    if return_code != 0:
                        exit_failures.append(f"{version}={return_code}")
                    results[version]["peak_memory_bytes"] = worker.peak_memory_bytes()
                if exit_failures:
                    raise RuntimeError(
                        "Workers exited unsuccessfully: " + ", ".join(exit_failures)
                    )
            for version in repositories:
                warm = results[version]["warm_runs"]
                results[version]["warm_median_seconds"] = statistics.median(
                    item["total_seconds"] for item in warm
                )
                results[version]["warm_plan_median_seconds"] = statistics.median(
                    item["planning_seconds"] for item in warm
                )
                results[version]["warm_execution_median_seconds"] = statistics.median(
                    item["execution_seconds"] for item in warm
                )
            payload["scenarios"].append({
                "id": scenario["id"],
                "name": scenario["name"],
                **results,
            })
            print(f"Completed {scenario['name']}", flush=True)
    finally:
        pass
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    _write_report(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-root", type=Path, required=True)
    parser.add_argument("--redesigned-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.old_root, arguments.redesigned_root, arguments.output)
    print(f"Wrote {arguments.output} and {arguments.output.with_suffix('.json')}")


if __name__ == "__main__":
    main()
