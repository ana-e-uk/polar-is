"""Persistent worker used by the old-versus-redesigned storage benchmark."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np


def _result_metrics(result, variable: str) -> dict[str, Any]:
    timestamps = 0
    spatial_cells = 0
    valid_values = 0
    result_bytes = 0
    datasets = []
    shapes = []
    for group in result.groups:
        data = group.data
        timestamps += int(data.sizes.get("timestamp", 0))
        if "cell" in data.sizes:
            spatial_cells += int(data.sizes["cell"])
        else:
            y_size = int(data.sizes.get("grid_y", data.sizes.get("y", 0)))
            x_size = int(data.sizes.get("grid_x", data.sizes.get("x", 0)))
            spatial_cells += y_size * x_size
        shapes.append(dict(data.sizes))
        if variable in data:
            values = np.asarray(data[variable].values)
            valid_values += int(np.isfinite(values).sum())
        result_bytes += group.file_path.stat().st_size
        datasets.append(group.source.dataset)
    return {
        "groups": len(result.groups),
        "timestamps": timestamps,
        "spatial_cells": spatial_cells,
        "valid_values": valid_values,
        "result_bytes": result_bytes,
        "datasets": datasets,
        "shapes": shapes,
        "warnings": list(result.warnings),
    }


def _direct_query(query: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    import storage.query_data.executor as executor
    from polaris.config import get_settings

    planning_seconds = 0.0
    original_plan_query = executor.plan_query

    def timed_plan_query(*args, **kwargs):
        nonlocal planning_seconds
        started = time.perf_counter()
        try:
            return original_plan_query(*args, **kwargs)
        finally:
            planning_seconds += time.perf_counter() - started

    executor.plan_query = timed_plan_query
    try:
        started = time.perf_counter()
        result = executor.execute_query(
            query,
            settings=get_settings(),
            output_dir=output_dir,
        )
        total_seconds = time.perf_counter() - started
    finally:
        executor.plan_query = original_plan_query
    return {
        "total_seconds": total_seconds,
        "planning_seconds": planning_seconds,
        "execution_seconds": total_seconds - planning_seconds,
        **_result_metrics(result, query["variable"]),
    }


def _api_query(query: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    os.environ["POLARIS_ACCESS_MODE"] = "anonymous"
    from fastapi.testclient import TestClient

    from api.interface.app import api_settings, app
    from polaris.config import get_settings
    from polaris.services.job_service import job_service

    settings = replace(get_settings(), _query_results=output_dir)
    app.dependency_overrides[api_settings] = lambda: settings
    job_service.clear()
    started = time.perf_counter()
    try:
        # Do not enter TestClient's lifespan here. Startup cleanup targets the
        # repository output tree, while benchmark artifacts live in /tmp.
        client = TestClient(app)
        response = client.post(
            "/api/v1/jobs",
            json={"query": query, "outputs": ["plot-json", "netcdf"]},
        )
        if response.status_code != 202:
            return {
                "total_seconds": time.perf_counter() - started,
                "status": f"HTTP {response.status_code}",
                "groups": 0,
                "error": response.text,
            }
        job = response.json()
        while job["status"] not in {"completed", "failed", "cancelled"}:
            time.sleep(0.01)
            poll = client.get(job["status_url"])
            poll.raise_for_status()
            job = poll.json()
        elapsed = time.perf_counter() - started
        if job["status"] != "completed":
            raise RuntimeError(f"API job ended with {job['status']}: {job.get('error')}")
        result = job["result"]
        return {
            "total_seconds": elapsed,
            "status": "completed",
            "groups": len(result["groups"]),
            "warnings": result.get("warnings", []),
        }
    finally:
        app.dependency_overrides.clear()
        job_service.clear()


def main() -> None:
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("mode") == "stop":
            return
        try:
            output_dir = Path(request["output_dir"])
            output_dir.mkdir(parents=True, exist_ok=True)
            if request["mode"] == "direct":
                result = _direct_query(request["query"], output_dir)
            elif request["mode"] == "api":
                result = _api_query(request["query"], output_dir)
            else:
                raise ValueError(f"Unknown worker mode: {request['mode']}")
            print(json.dumps({"ok": True, "result": result}), flush=True)
        except BaseException as error:
            print(
                json.dumps({
                    "ok": False,
                    "error": f"{type(error).__name__}: {error}",
                }),
                flush=True,
            )


if __name__ == "__main__":
    main()
