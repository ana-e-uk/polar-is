"""Execute planned queries from time-partitioned products."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from functools import lru_cache
import json
import operator
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import xarray as xr

from polaris.config import Settings, get_settings
from storage.catalog import stable_128_bit_id
from storage.ingest_data.aggregate_data import (
    AGGREGATE_STATISTICS,
    add_aggregate_statistics,
)
from storage.query_data.query_data import (
    BlockGroupCoverage,
    BoundingBox,
    MatchingBlockGroup,
    Query,
    QueryPlan,
    plan_query,
)


@dataclass(frozen=True)
class SourceInfo:
    repository: str
    dataset: str
    variable: str
    additional_parameters: dict[str, Any]
    native_temporal_resolutions: tuple[str, ...]
    native_spatial_resolutions: tuple[Any, ...]
    partition_ids: tuple[str, ...]


@dataclass(frozen=True)
class GroupResult:
    group_id: str
    data: xr.Dataset
    file_path: Path
    source: SourceInfo
    units: str | None
    grid_id: str
    grid_window: tuple[int, int, int, int]
    hit_set: frozenset[tuple[str, datetime]]
    miss_set: frozenset[tuple[str, datetime]]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class QueryResult:
    query_id: str
    function: str
    groups: tuple[GroupResult, ...]
    unmatched_miss_set: frozenset[tuple[str, datetime]]
    warnings: tuple[str, ...]


def _query_id(query: Query) -> str:
    return stable_128_bit_id(asdict(query))


def _group_id(group: MatchingBlockGroup) -> str:
    return stable_128_bit_id(
        {
            "dataset_variant_id": group.dataset_variant_id,
            "variable": group.variable,
            "grid_id": group.grid_id,
        }
    )


def _coarsen_coordinate(
    coordinate: xr.DataArray,
    factor: int,
    *,
    circular: bool = False,
) -> xr.DataArray:
    if factor == 1:
        return coordinate
    windows = {
        dimension: factor
        for dimension in ("y", "x")
        if dimension in coordinate.dims
    }
    if circular:
        radians = np.deg2rad(coordinate)
        sine = np.sin(radians).coarsen(windows, boundary="pad").mean()
        cosine = np.cos(radians).coarsen(windows, boundary="pad").mean()
        result = np.rad2deg(np.arctan2(sine, cosine)) % 360
    else:
        result = coordinate.coarsen(windows, boundary="pad").mean()
    result.attrs = coordinate.attrs.copy()
    return result


def _product_grid(grid: xr.Dataset, factor: int) -> xr.Dataset:
    latitude = _coarsen_coordinate(grid["latitude"], factor)
    longitude = _coarsen_coordinate(
        grid["longitude"], factor, circular=True
    )
    result = xr.Dataset(coords={"latitude": latitude, "longitude": longitude})
    result["cell_area"] = grid["cell_area"].coarsen(
        {"y": factor, "x": factor}, boundary="pad"
    ).sum()
    for name in ("projection_x", "projection_y"):
        if name in grid.coords:
            result = result.assign_coords(
                {name: _coarsen_coordinate(grid[name], factor)}
            )
    if "crs" in grid:
        result = result.assign_coords(crs=grid["crs"])
    return result


def _spatial_mask(data: xr.Dataset, region: BoundingBox) -> xr.DataArray:
    latitude, longitude = xr.broadcast(data["latitude"], data["longitude"])
    latitude = latitude.transpose("y", "x")
    longitude = (longitude % 360).transpose("y", "x")
    latitude_mask = (latitude >= region.south) & (latitude <= region.north)
    if region.west < region.east:
        longitude_mask = (longitude >= region.west) & (longitude <= region.east)
    elif region.west > region.east:
        longitude_mask = (longitude >= region.west) | (longitude <= region.east)
    else:
        longitude_mask = xr.ones_like(longitude, dtype=bool)
    return latitude_mask & longitude_mask


def _local_slice(
    global_start: int,
    global_stop: int,
    partition_start: int,
    factor: int,
) -> slice:
    start = max(0, (global_start - partition_start) // factor)
    stop = max(start + 1, int(np.ceil((global_stop - partition_start) / factor)))
    return slice(start, stop)


def _spatial_extent(mask: xr.DataArray) -> tuple[slice, slice] | None:
    """Return the smallest y/x rectangle containing every true cell."""
    y_indices = np.flatnonzero(mask.any(dim="x").values)
    x_indices = np.flatnonzero(mask.any(dim="y").values)
    if not y_indices.size or not x_indices.size:
        return None
    return (
        slice(int(y_indices[0]), int(y_indices[-1] + 1)),
        slice(int(x_indices[0]), int(x_indices[-1] + 1)),
    )


def _required_statistics(query: Query) -> tuple[str, ...]:
    if query.aggregation_method == "mean":
        return ("polaris_weighted_sum", "polaris_weight_sum")
    if query.aggregation_method == "min":
        return ("polaris_min",)
    return ("polaris_max",)


@lru_cache(maxsize=16)
def _cached_grid(path: str, modified_ns: int) -> xr.Dataset:
    """Load one immutable canonical grid once per process and file version."""
    del modified_ns
    with xr.open_dataset(path) as opened:
        return opened.load()


def _load_grid(path: Path) -> xr.Dataset:
    return _cached_grid(str(path), path.stat().st_mtime_ns)


def _read_partition(
    plan: QueryPlan,
    group: MatchingBlockGroup,
    record: dict[str, Any],
    grid: xr.Dataset,
    storage_root: Path,
) -> xr.Dataset | None:
    factor = int(record["coarseness_factor"])
    product_grid = _product_grid(grid, factor)
    windows = record["query_windows"]
    y_start = min(window["grid_y_start"] for window in windows)
    y_stop = max(window["grid_y_stop"] for window in windows)
    x_start = min(window["grid_x_start"] for window in windows)
    x_stop = max(window["grid_x_stop"] for window in windows)
    y_slice = _local_slice(
        y_start, y_stop, int(record["grid_y_start"]), factor
    )
    x_slice = _local_slice(
        x_start, x_stop, int(record["grid_x_start"]), factor
    )
    grid_y_offset = int(record["grid_y_start"]) // factor
    grid_x_offset = int(record["grid_x_start"]) // factor
    grid_slice = product_grid.isel(
        y=slice(grid_y_offset + y_slice.start, grid_y_offset + y_slice.stop),
        x=slice(grid_x_offset + x_slice.start, grid_x_offset + x_slice.stop),
    )
    # Bucket lookup windows are only a coarse first pass. Refine them against
    # the canonical coordinates before opening product variables so a small
    # regional query reads only intersecting NetCDF chunks.
    exact_extent = _spatial_extent(_spatial_mask(grid_slice, plan.query.region))
    if exact_extent is None:
        return None
    exact_y, exact_x = exact_extent
    y_slice = slice(y_slice.start + exact_y.start, y_slice.start + exact_y.stop)
    x_slice = slice(x_slice.start + exact_x.start, x_slice.start + exact_x.stop)
    grid_slice = grid_slice.isel(y=exact_y, x=exact_x)

    path = storage_root / record["relative_path"]
    required_statistics = _required_statistics(plan.query)
    with xr.open_dataset(path) as opened:
        selected = opened.sel(
            timestamp=slice(plan.query.time_start, plan.query.time_end)
        ).isel(y=y_slice, x=x_slice)
        if all(name in selected for name in required_statistics):
            selected = selected[list(required_statistics)]
        elif plan.query.variable in selected:
            selected = selected[[plan.query.variable]]
        else:
            raise ValueError(
                f"Product {record['partition_id']} is missing variables for "
                f"{plan.query.aggregation_method!r} aggregation"
            )
        data = selected.load()
    if data.sizes.get("timestamp", 0) == 0:
        return None

    data = data.assign_coords(
        latitude=grid_slice["latitude"],
        longitude=grid_slice["longitude"],
    )
    for name in ("projection_x", "projection_y", "crs"):
        if name in grid_slice:
            data = data.assign_coords({name: grid_slice[name]})
    if not all(name in data for name in required_statistics):
        data = add_aggregate_statistics(
            data,
            plan.query.variable,
            grid_slice["cell_area"].reset_coords(drop=True),
        )
    mask = _spatial_mask(data, plan.query.region)
    if not bool(mask.any().item()):
        return None
    if plan.query.aggregation_method == "mean":
        valid = data["polaris_weight_sum"] > 0
    else:
        valid = data[required_statistics[0]].notnull()
    if "timestamp" in valid.dims:
        valid = valid.any(dim="timestamp")
    populated_extent = _spatial_extent(mask & valid)
    if populated_extent is None:
        return None
    populated_y, populated_x = populated_extent
    data = data.isel(y=populated_y, x=populated_x)
    mask = mask.isel(y=populated_y, x=populated_x)
    grid_slice = grid_slice.isel(y=populated_y, x=populated_x)
    y_slice = slice(
        y_slice.start + populated_y.start,
        y_slice.start + populated_y.stop,
    )
    x_slice = slice(
        x_slice.start + populated_x.start,
        x_slice.start + populated_x.stop,
    )
    for name, variable in tuple(data.data_vars.items()):
        if {"y", "x"}.issubset(variable.dims):
            data[name] = variable.where(mask)

    local_y = np.arange(y_slice.start, y_slice.stop)
    local_x = np.arange(x_slice.start, x_slice.stop)
    global_y = int(record["grid_y_start"]) + local_y * factor
    global_x = int(record["grid_x_start"]) + local_x * factor
    return data.rename({"y": "grid_y", "x": "grid_x"}).assign_coords(
        grid_y=global_y,
        grid_x=global_x,
    )


def _get_data(
    plan: QueryPlan,
    group: MatchingBlockGroup,
    settings: Settings | None = None,
) -> tuple[xr.Dataset | None, tuple[dict[str, Any], ...], tuple[str, ...]]:
    """Read, slice, mask, and combine one group of time partitions."""
    settings = settings or get_settings()
    grid_path = settings.grids_dir / f"{group.grid_id}.nc"
    partitions = []
    used = []
    warnings = []
    grid = _load_grid(grid_path)
    for record in group.blocks:
        data = _read_partition(
            plan,
            group,
            record,
            grid,
            settings.products_dir.parent,
        )
        if data is None:
            warnings.append(
                f"Partition {record['partition_id']} had no data after cropping."
            )
            continue
        partitions.append(data)
        used.append(record)
    if not partitions:
        return None, tuple(used), tuple(warnings)
    combined = xr.concat(
        partitions,
        dim="timestamp",
        join="exact",
        data_vars="all",
        coords="minimal",
        compat="override",
        combine_attrs="override",
    ).sortby("timestamp")
    timestamps = combined.get_index("timestamp")
    combined = combined.isel(timestamp=~timestamps.duplicated())
    return combined, tuple(used), tuple(warnings)


def _requested_values(data: xr.Dataset, query: Query) -> xr.DataArray:
    if query.aggregation_method == "mean":
        weights = data["polaris_weight_sum"]
        values = (data["polaris_weighted_sum"] / weights).where(weights > 0)
    elif query.aggregation_method == "min":
        values = data["polaris_min"]
    else:
        values = data["polaris_max"]
    values = values.rename(query.variable)
    for statistic in AGGREGATE_STATISTICS:
        if statistic in data and data[statistic].attrs:
            values.attrs = data[statistic].attrs.copy()
            break
    return values


def _collapse_data(
    data: xr.Dataset,
    query: Query,
    dimensions: str | tuple[str, ...],
) -> xr.Dataset:
    if query.aggregation_method == "mean":
        weighted_sum = data["polaris_weighted_sum"].sum(
            dimensions, skipna=True, min_count=1
        )
        weight_sum = data["polaris_weight_sum"].sum(
            dimensions, skipna=True, min_count=1
        )
        values = (weighted_sum / weight_sum).where(weight_sum > 0)
    elif query.aggregation_method == "min":
        values = data["polaris_min"].min(dimensions, skipna=True)
    else:
        values = data["polaris_max"].max(dimensions, skipna=True)
    values = values.rename(query.variable)
    statistic = {
        "mean": "polaris_weighted_sum",
        "min": "polaris_min",
        "max": "polaris_max",
    }[query.aggregation_method]
    values.attrs = data[statistic].attrs.copy()
    return values.to_dataset()


def _apply_predicate(data: xr.Dataset, query: Query) -> xr.Dataset:
    operations = {
        "lt": operator.lt,
        "le": operator.le,
        "eq": operator.eq,
        "ne": operator.ne,
        "ge": operator.ge,
        "gt": operator.gt,
    }
    values = data[query.variable]
    result = data.copy()
    result["matches"] = values.notnull() & operations[query.predicate](
        values, query.filter_value
    )
    result["matches"].attrs = {
        "predicate": query.predicate,
        "filter_value": query.filter_value,
    }
    return result


def _compute_result(data: xr.Dataset, query: Query) -> xr.Dataset:
    if query.function == "get-data":
        return _requested_values(data, query).to_dataset()
    if query.function == "timeseries":
        return _collapse_data(data, query, ("grid_y", "grid_x"))
    if query.function == "heatmap":
        return _collapse_data(data, query, "timestamp")
    if query.function == "find-time":
        return _apply_predicate(
            _collapse_data(data, query, ("grid_y", "grid_x")), query
        )
    if query.function == "find-area":
        return _apply_predicate(_collapse_data(data, query, "timestamp"), query)
    raise ValueError(f"Unsupported function: {query.function!r}")


def _source_info(
    group: MatchingBlockGroup,
    records: tuple[dict[str, Any], ...],
) -> SourceInfo:
    source_resolutions = tuple(
        dict.fromkeys(
            record.get("source_temporal_resolution") for record in records
        )
    )
    return SourceInfo(
        repository=group.repository,
        dataset=group.dataset,
        variable=group.variable,
        additional_parameters=group.additional_parameters,
        native_temporal_resolutions=source_resolutions,
        native_spatial_resolutions=(),
        partition_ids=tuple(record["partition_id"] for record in records),
    )


def _decorate_result(
    data: xr.Dataset,
    plan: QueryPlan,
    group: MatchingBlockGroup,
    query_id: str,
    group_id: str,
    records: tuple[dict[str, Any], ...],
) -> xr.Dataset:
    result = data.copy()
    result.attrs.update(
        {
            "query_id": query_id,
            "group_id": group_id,
            "function": plan.query.function,
            "repository": group.repository,
            "dataset": group.dataset,
            "variable": group.variable,
            "additional_parameters": json.dumps(
                group.additional_parameters, sort_keys=True
            ),
            "coarseness_factor": plan.requested_data_grid.coarseness_factor,
            "time_unit": plan.requested_data_grid.time_unit,
            "aggregation_method": plan.query.aggregation_method,
            "grid_id": group.grid_id,
            "grid_window": json.dumps(group.grid_window),
            "partition_ids": json.dumps(
                [record["partition_id"] for record in records]
            ),
        }
    )
    return result


def _write_result(data: xr.Dataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    try:
        data.to_netcdf(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def execute_query(
    query: Query | Mapping[str, Any],
    settings: Settings | None = None,
    output_dir: Path | None = None,
) -> QueryResult:
    """Plan and execute one query, returning one NetCDF result per group."""
    settings = settings or get_settings()
    plan = plan_query(query, settings)
    query_id = _query_id(plan.query)
    output_dir = Path(output_dir or settings._query_results)
    coverage_by_group = {
        id(coverage.group): coverage for coverage in plan.coverage.groups
    }
    results = []
    warnings = list(plan.coverage.warnings)
    for group in plan.block_groups:
        coverage: BlockGroupCoverage = coverage_by_group[id(group)]
        source_data, records, reading_warnings = _get_data(plan, group, settings)
        warnings.extend(reading_warnings)
        if source_data is None:
            warnings.append(
                f"No data could be read for {group.repository}/{group.dataset}."
            )
            continue
        group_id = _group_id(group)
        result_data = _decorate_result(
            _compute_result(source_data, plan.query),
            plan,
            group,
            query_id,
            group_id,
            records,
        )
        path = output_dir / query_id / plan.query.function / f"{group_id}.nc"
        _write_result(result_data, path)
        source = _source_info(group, records)
        results.append(
            GroupResult(
                group_id=group_id,
                data=result_data,
                file_path=path,
                source=source,
                units=result_data[plan.query.variable].attrs.get("units"),
                grid_id=group.grid_id,
                grid_window=group.grid_window,
                hit_set=coverage.hit_set,
                miss_set=coverage.miss_set,
                warnings=coverage.warnings + reading_warnings,
            )
        )
    return QueryResult(
        query_id=query_id,
        function=plan.query.function,
        groups=tuple(results),
        unmatched_miss_set=plan.coverage.unmatched_miss_set,
        warnings=tuple(warnings),
    )
