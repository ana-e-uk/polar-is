"""Execute one validated job and build its downloadable artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

from polaris.config import Settings
from polaris.services.result_serializer import serialize_group, serialize_result
from polaris.visualization.plot_model import build_plot_model
from polaris.visualization.png_renderer import render_png
from storage.query_data.executor import QueryResult, execute_query
from storage.query_data.query_data import (
    _expected_timestamps,
    normalize_query,
    plan_query,
)


SUPPORTED_OUTPUTS = frozenset({"plot-json", "png", "netcdf"})
PLOT_FUNCTIONS = frozenset({"timeseries", "heatmap", "find-time", "find-area"})


@dataclass(frozen=True)
class OutputArtifact:
    group_id: str
    kind: str
    path: Path
    media_type: str
    filename: str


@dataclass(frozen=True)
class QueryArtifacts:
    result: dict[str, Any]
    groups: tuple[dict[str, Any], ...]
    outputs: tuple[OutputArtifact, ...]
    output_root: Path


@dataclass(frozen=True)
class QueryEstimate:
    """Conservative work estimate made without opening data blocks."""

    spatial_cells: int
    time_intervals: int
    matching_blocks: int
    result_values: int
    result_groups: int


_TIME_UNIT_RESOLUTIONS = {
    "Hour": "1H",
    "Day": "1D",
    "Month": "1MS",
    "Year": "1YS",
}


def _positive_limit(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _longitude_span(west: float, east: float) -> float:
    if west < east:
        return east - west
    if west > east:
        return 360.0 - west + east
    return 360.0


def _estimated_group_cells(query, group, settings: Settings) -> int:
    try:
        grid = settings.name_docs[group.repository][group.dataset]["grid"]
        resolution = float(grid["resolution"][0]) * query.coarseness_factor
        units = str(grid["units"]).lower()
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError(
            "Polar-is cannot safely estimate the selected dataset's grid size"
        ) from error
    if not math.isfinite(resolution) or resolution <= 0:
        raise ValueError(
            "Polar-is cannot safely estimate the selected dataset's grid size"
        )

    latitude_span = query.region.north - query.region.south
    longitude_span = _longitude_span(query.region.west, query.region.east)
    if units in {"degree", "degrees"}:
        rows = math.ceil(latitude_span / resolution) + 1
        columns = math.ceil(longitude_span / resolution) + 1
    elif units in {"km", "kilometer", "kilometers"}:
        # Use the latitude closest to the equator for a conservative longitude
        # width. The extra boundary row/column avoids underestimating partial
        # grid cells along the requested envelope.
        closest_latitude = (
            0.0
            if query.region.south <= 0 <= query.region.north
            else min(abs(query.region.south), abs(query.region.north))
        )
        latitude_km = latitude_span * 111.32
        longitude_km = (
            longitude_span
            * 111.32
            * math.cos(math.radians(closest_latitude))
        )
        rows = math.ceil(latitude_km / resolution) + 1
        columns = math.ceil(longitude_km / resolution) + 1
    else:
        raise ValueError(
            f"Polar-is cannot estimate grid sizes expressed in {grid['units']!r}"
        )
    return max(1, rows) * max(1, columns)


def _estimated_group_intervals(query, group) -> int:
    if query.time_unit != "Source":
        resolutions = (_TIME_UNIT_RESOLUTIONS[query.time_unit],)
    else:
        resolutions = tuple(
            sorted(
                {
                    str(record.get("temporal_resolution"))
                    for record in group.blocks
                    if record.get("temporal_resolution")
                }
            )
        )
        if not resolutions:
            raise ValueError(
                "Polar-is cannot safely estimate the selected source time resolution"
            )
    try:
        return max(len(_expected_timestamps(query, value)) for value in resolutions)
    except ValueError as error:
        raise ValueError(
            "Polar-is cannot safely estimate the selected source time resolution"
        ) from error


def estimate_query(query, settings: Settings) -> QueryEstimate:
    """Estimate public-query cost using metadata and configured grid sizes."""
    plan = plan_query(query, settings)
    group_estimates = [
        (
            _estimated_group_cells(plan.query, group, settings),
            _estimated_group_intervals(plan.query, group),
        )
        for group in plan.block_groups
    ]
    return QueryEstimate(
        spatial_cells=sum(cells for cells, _ in group_estimates),
        time_intervals=max((times for _, times in group_estimates), default=0),
        matching_blocks=len(plan.matching_blocks),
        result_values=sum(cells * times for cells, times in group_estimates),
        result_groups=len(plan.block_groups),
    )


def _enforce_query_limits(estimate: QueryEstimate) -> None:
    limits = (
        (
            "spatial cells",
            estimate.spatial_cells,
            "POLARIS_MAX_SPATIAL_CELLS",
            25_000,
        ),
        (
            "matching storage blocks",
            estimate.matching_blocks,
            "POLARIS_MAX_MATCHING_BLOCKS",
            100,
        ),
        (
            "result values",
            estimate.result_values,
            "POLARIS_MAX_RESULT_VALUES",
            500_000,
        ),
        ("result groups", estimate.result_groups, "POLARIS_MAX_RESULT_GROUPS", 5),
    )
    for label, actual, environment_name, default in limits:
        maximum = _positive_limit(environment_name, default)
        if actual > maximum:
            raise ValueError(
                f"Estimated {label} ({actual:,}) exceed the conference limit "
                f"({maximum:,}); reduce the region, time range, or resolution"
            )


def validate_job_request(
    query: dict[str, Any], outputs: Iterable[str], settings: Settings
) -> tuple[str, ...]:
    """Validate a job before it enters the bounded worker queue."""
    requested = tuple(dict.fromkeys(outputs))
    if not requested:
        raise ValueError("At least one output must be requested")
    unsupported = sorted(set(requested) - SUPPORTED_OUTPUTS)
    if unsupported:
        raise ValueError(f"Unsupported output type: {', '.join(unsupported)}")

    normalized = normalize_query(query, settings)
    if "png" in requested and normalized.function not in PLOT_FUNCTIONS:
        raise ValueError(f"PNG output is not supported for {normalized.function!r}")

    maximum_days = _positive_limit("POLARIS_MAX_QUERY_DAYS", 31)
    duration = normalized.time_end - normalized.time_start
    if duration > timedelta(days=maximum_days):
        raise ValueError(
            f"Query duration exceeds the {maximum_days}-day prototype limit"
        )
    _enforce_query_limits(estimate_query(normalized, settings))
    return requested


def _output_url(job_id: str, group_id: str, kind: str) -> str:
    return f"/api/v1/jobs/{job_id}/outputs/{group_id}/{kind}"


def execute_job(
    job_id: str,
    query: dict[str, Any],
    outputs: tuple[str, ...],
    settings: Settings,
) -> QueryArtifacts:
    """Run the shared executor and create all requested job artifacts."""
    output_root = settings._query_results / "jobs" / job_id
    result: QueryResult = execute_query(
        query, settings, output_dir=output_root / "netcdf"
    )
    artifacts: list[OutputArtifact] = []
    manifest_groups: list[dict[str, Any]] = []

    def netcdf_url(group) -> str:
        return (
            _output_url(job_id, group.group_id, "netcdf")
            if "netcdf" in outputs
            else ""
        )

    serialized_result = serialize_result(result, settings, netcdf_url)
    serialized_by_group = {
        group["group_id"]: group for group in serialized_result["groups"]
    }

    for group in result.groups:
        manifest: dict[str, Any] = {
            "group_id": group.group_id,
            "source": group.source.dataset,
        }
        if "plot-json" in outputs:
            plot_json_path = output_root / "plot-json" / f"{group.group_id}.json"
            plot_json_path.parent.mkdir(parents=True, exist_ok=True)
            plot_json_path.write_text(
                json.dumps(serialized_by_group[group.group_id], allow_nan=False)
            )
            artifacts.append(
                OutputArtifact(
                    group.group_id,
                    "plot-json",
                    plot_json_path,
                    "application/json",
                    f"polar-is-{job_id}-{group.group_id}.json",
                )
            )
            manifest["plot_json_url"] = _output_url(
                job_id, group.group_id, "plot-json"
            )
        if "png" in outputs:
            png_path = output_root / "png" / f"{group.group_id}.png"
            render_png(build_plot_model(group, result.function), png_path)
            artifacts.append(
                OutputArtifact(
                    group.group_id,
                    "png",
                    png_path,
                    "image/png",
                    f"polar-is-{job_id}-{group.group_id}.png",
                )
            )
            manifest["png_url"] = _output_url(job_id, group.group_id, "png")
        if "netcdf" in outputs:
            artifacts.append(
                OutputArtifact(
                    group.group_id,
                    "netcdf",
                    group.file_path,
                    "application/x-netcdf",
                    f"polar-is-{job_id}-{group.group_id}.nc",
                )
            )
            manifest["data_url"] = _output_url(
                job_id, group.group_id, "netcdf"
            )
        else:
            # The shared executor always materializes NetCDF atomically. Remove
            # that intermediate when the caller only requested plot artifacts.
            group.file_path.unlink(missing_ok=True)
        manifest_groups.append(manifest)

    maximum_bytes = _positive_limit("POLARIS_MAX_OUTPUT_BYTES", 50 * 1024 * 1024)
    output_bytes = sum(item.path.stat().st_size for item in artifacts)
    if output_bytes > maximum_bytes:
        raise ValueError(
            f"Generated output exceeds the {maximum_bytes}-byte prototype limit"
        )
    return QueryArtifacts(
        result=serialized_result,
        groups=tuple(manifest_groups),
        outputs=tuple(artifacts),
        output_root=output_root,
    )
