"""Execute a planned query and write one result for each block group."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import operator
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import xarray as xr

from polaris.config import Settings, get_settings
from storage.ingest_data.aggregate_data import (
    AGGREGATE_STATISTICS,
    add_aggregate_statistics,
)
from storage.ingest_data.make_data_blocks import (
    block_path,
    spatially_crop_block,
)
from storage.grid_topology import transformer_from_grid_mapping
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
    block_ids: tuple[str, ...]


@dataclass(frozen=True)
class GroupResult:
    group_id: str
    data: xr.Dataset
    file_path: Path
    source: SourceInfo
    units: str | None
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


def _stable_id(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.blake2b(encoded, digest_size=16).hexdigest()


def _query_id(query: Query) -> str:
    return _stable_id(asdict(query))


def _group_id(group: MatchingBlockGroup) -> str:
    return _stable_id(
        {
            "repository": group.repository,
            "dataset": group.dataset,
            "variable": group.variable,
            "additional_parameters": group.additional_parameters,
        }
    )


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


def _spatial_coordinate_values(
    data: xr.Dataset,
    name: str,
    cell_indices: np.ndarray,
) -> np.ndarray:
    """Broadcast one topology coordinate to y/x and select flattened cells."""
    coordinate = data[name]
    if coordinate.dims == ("y",):
        values = np.broadcast_to(
            np.asarray(coordinate.values)[:, None],
            (data.sizes["y"], data.sizes["x"]),
        )
    elif coordinate.dims == ("x",):
        values = np.broadcast_to(
            np.asarray(coordinate.values)[None, :],
            (data.sizes["y"], data.sizes["x"]),
        )
    elif coordinate.dims == ("y", "x"):
        values = np.asarray(coordinate.values)
    else:
        raise ValueError(f"Topology coordinate {name!r} has unsupported dimensions")
    return values.reshape(-1)[cell_indices]


def _inferred_curvilinear_vertices(
    data: xr.Dataset,
) -> tuple[np.ndarray, np.ndarray]:
    """Infer a vertex lattice when an irregular source provides centers only."""
    latitude = np.asarray(data["latitude"].values, dtype=float)
    longitude = np.rad2deg(
        np.unwrap(np.unwrap(np.deg2rad(data["longitude"].values), axis=1), axis=0)
    )

    def vertices(values: np.ndarray) -> np.ndarray:
        padded = np.empty((values.shape[0] + 2, values.shape[1] + 2), dtype=float)
        padded[1:-1, 1:-1] = values
        if values.shape[0] > 1:
            padded[0, 1:-1] = 2 * values[0] - values[1]
            padded[-1, 1:-1] = 2 * values[-1] - values[-2]
        else:
            padded[0, 1:-1] = padded[-1, 1:-1] = values[0]
        if values.shape[1] > 1:
            padded[1:-1, 0] = 2 * values[:, 0] - values[:, 1]
            padded[1:-1, -1] = 2 * values[:, -1] - values[:, -2]
        else:
            padded[1:-1, 0] = padded[1:-1, -1] = values[:, 0]
        padded[0, 0] = padded[0, 1] + padded[1, 0] - padded[1, 1]
        padded[0, -1] = padded[0, -2] + padded[1, -1] - padded[1, -2]
        padded[-1, 0] = padded[-1, 1] + padded[-2, 0] - padded[-2, 1]
        padded[-1, -1] = padded[-1, -2] + padded[-2, -1] - padded[-2, -2]
        return (
            padded[:-1, :-1]
            + padded[:-1, 1:]
            + padded[1:, :-1]
            + padded[1:, 1:]
        ) / 4

    return vertices(latitude), vertices(longitude)


def _cell_corners(
    data: xr.Dataset,
    cell_indices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return four geographic corners for each selected native/coarse cell."""
    y_indices, x_indices = np.unravel_index(
        cell_indices, (data.sizes["y"], data.sizes["x"])
    )
    # Explicit geographic bounds are authoritative for a rectilinear grid.
    # Check them before projected CRS metadata so a stale auxiliary CRS cannot
    # rotate otherwise regular latitude/longitude cells.
    if "latitude_bounds" in data and "longitude_bounds" in data:
        latitude_bounds = np.asarray(data["latitude_bounds"].values)[y_indices]
        longitude_bounds = np.asarray(data["longitude_bounds"].values)[x_indices]
        south = np.min(latitude_bounds, axis=1)
        north = np.max(latitude_bounds, axis=1)
        west = np.min(longitude_bounds, axis=1)
        east = np.max(longitude_bounds, axis=1)
        return (
            np.column_stack((south, south, north, north)),
            np.column_stack((west, east, east, west)) % 360,
        )

    transformer = transformer_from_grid_mapping(data)
    if transformer is not None:
        crs = data["crs"].attrs
        x_origin = float(crs["polaris_projection_x_origin"])
        y_origin = float(crs["polaris_projection_y_origin"])
        x_step = float(crs["polaris_projection_x_step"])
        y_step = float(crs["polaris_projection_y_step"])
        x_start = _spatial_coordinate_values(data, "source_x_start", cell_indices)
        x_stop = _spatial_coordinate_values(data, "source_x_stop", cell_indices)
        y_start = _spatial_coordinate_values(data, "source_y_start", cell_indices)
        y_stop = _spatial_coordinate_values(data, "source_y_stop", cell_indices)
        x_edges = np.column_stack(
            (x_origin + (x_start - 0.5) * x_step,
             x_origin + (x_stop - 0.5) * x_step)
        )
        y_edges = np.column_stack(
            (y_origin + (y_start - 0.5) * y_step,
             y_origin + (y_stop - 0.5) * y_step)
        )
        west, east = np.min(x_edges, axis=1), np.max(x_edges, axis=1)
        south, north = np.min(y_edges, axis=1), np.max(y_edges, axis=1)
        projected_x = np.column_stack((west, east, east, west))
        projected_y = np.column_stack((south, south, north, north))
        longitude, latitude = transformer.transform(projected_x, projected_y)
        return np.asarray(latitude), np.asarray(longitude) % 360

    vertex_latitude, vertex_longitude = _inferred_curvilinear_vertices(data)
    latitude = np.column_stack(
        (
            vertex_latitude[y_indices, x_indices],
            vertex_latitude[y_indices, x_indices + 1],
            vertex_latitude[y_indices + 1, x_indices + 1],
            vertex_latitude[y_indices + 1, x_indices],
        )
    )
    longitude = np.column_stack(
        (
            vertex_longitude[y_indices, x_indices],
            vertex_longitude[y_indices, x_indices + 1],
            vertex_longitude[y_indices + 1, x_indices + 1],
            vertex_longitude[y_indices + 1, x_indices],
        )
    )
    return latitude, longitude % 360


def _block_to_cells(
    data: xr.Dataset,
    query: Query,
    bucket_id: str,
    cell_namespace: str,
) -> xr.Dataset | None:
    if "timestamp" not in data.dims:
        return None
    data = data.sel(timestamp=slice(query.time_start, query.time_end))
    if data.sizes.get("timestamp", 0) == 0:
        return None

    query_mask = _spatial_mask(data, query.region)
    if not bool(query_mask.any().item()):
        return None
    data = spatially_crop_block(data, query_mask)
    if not all(name in data for name in AGGREGATE_STATISTICS):
        data = add_aggregate_statistics(data, query.variable)

    query_mask = _spatial_mask(data, query.region)
    valid_cells = (data["polaris_valid_count"] > 0).any(dim="timestamp")
    cell_mask = (query_mask & valid_cells).stack(cell=("y", "x"))
    cell_indices = np.flatnonzero(cell_mask.values)
    if cell_indices.size == 0:
        return None

    required_topology = {
        "source_y_index",
        "source_x_index",
        "source_y_start",
        "source_y_stop",
        "source_x_start",
        "source_x_stop",
        "grid_y_index",
        "grid_x_index",
    }
    missing_topology = sorted(required_topology - set(data.coords))
    if missing_topology:
        raise ValueError(
            "Stored block predates explicit grid topology; rebuild it before querying "
            f"(missing: {', '.join(missing_topology)})"
        )

    names = [query.variable, *AGGREGATE_STATISTICS]
    cells = data[names].stack(cell=("y", "x")).isel(cell=cell_indices)
    latitude, longitude = xr.broadcast(data["latitude"], data["longitude"])
    latitude = latitude.transpose("y", "x").stack(cell=("y", "x"))
    longitude = (longitude % 360).transpose("y", "x").stack(cell=("y", "x"))
    latitude_values = latitude.isel(cell=cell_indices).values
    longitude_values = longitude.isel(cell=cell_indices).values
    topology = {
        name: _spatial_coordinate_values(data, name, cell_indices)
        for name in required_topology
    }
    cell_keys = np.asarray([
        f"{cell_namespace}:c{query.coarseness_factor}:"
        f"{int(y_index)}:{int(x_index)}"
        for y_index, x_index in zip(
            topology["grid_y_index"], topology["grid_x_index"]
        )
    ])
    corner_latitude, corner_longitude = _cell_corners(data, cell_indices)
    coordinate_values: dict[str, Any] = {
        "cell": cell_keys,
        "cell_id": ("cell", cell_keys),
        "latitude": ("cell", latitude_values),
        "longitude": ("cell", longitude_values),
        "bucket_id": ("cell", np.full(cell_keys.size, bucket_id, dtype=str)),
        "vertex": np.arange(4, dtype=np.int8),
        "corner_latitude": (("cell", "vertex"), corner_latitude),
        "corner_longitude": (("cell", "vertex"), corner_longitude),
    }
    for name, values in topology.items():
        coordinate_values[name] = ("cell", values.astype(np.int64))
    for name in ("projection_x", "projection_y"):
        if name in data.coords:
            coordinate_values[name] = (
                "cell",
                _spatial_coordinate_values(data, name, cell_indices),
            )
    cells = cells.reset_index("cell", drop=True).assign_coords(
        coordinate_values
    )
    for name in names:
        cells[name] = cells[name].transpose("timestamp", "cell")
    return cells.sortby("cell").load()


def _get_data(
    plan: QueryPlan,
    group: MatchingBlockGroup,
) -> tuple[
    xr.Dataset | None,
    tuple[dict[str, Any], ...],
    tuple[str, ...],
]:
    """Derive paths, open blocks, crop them, and combine one block group."""
    blocks = []
    used_records = []
    warnings = []
    for record in group.blocks:
        path = block_path(
            plan.spatial_level,
            record["bucket_id"],
            record["block_id"],
        )
        with xr.open_dataset(path) as data:
            cells = _block_to_cells(
                data,
                plan.query,
                record["bucket_id"],
                _group_id(group),
            )
        if cells is not None:
            blocks.append(cells)
            used_records.append(record)
        else:
            warnings.append(
                f"Block {record['block_id']} had no cells after coordinate cropping."
            )
    if not blocks:
        return None, tuple(used_records), tuple(warnings)

    combined = xr.concat(
        blocks,
        dim="cell",
        join="outer",
        combine_attrs="override",
        data_vars="all",
        coords="minimal",
        compat="override",
    )
    if combined.get_index("cell").has_duplicates:
        combined = combined.groupby("cell").first(skipna=True)
    combined = combined.sortby(["timestamp", "cell"])
    timestamps = combined.get_index("timestamp")
    combined = combined.isel(timestamp=~timestamps.duplicated())
    cell_ids = combined["cell"].values.astype(str)
    combined = combined.assign_coords(cell_id=("cell", cell_ids))
    combined = combined.assign_coords(cell=np.arange(combined.sizes["cell"]))
    return combined, tuple(used_records), tuple(warnings)


def _requested_values(data: xr.Dataset, query: Query) -> xr.DataArray:
    if query.aggregation_method == "mean":
        weights = data["polaris_weight_sum"]
        values = (data["polaris_weighted_sum"] / weights).where(weights > 0)
    elif query.aggregation_method == "min":
        values = data["polaris_min"]
    else:
        values = data["polaris_max"]
    values = values.rename(query.variable)
    values.attrs = data[query.variable].attrs.copy()
    return values


def _collapse_data(
    data: xr.Dataset,
    query: Query,
    dimension: str,
) -> xr.Dataset:
    if query.aggregation_method == "mean":
        weighted_sum = data["polaris_weighted_sum"].sum(
            dimension, skipna=True, min_count=1
        )
        weight_sum = data["polaris_weight_sum"].sum(
            dimension, skipna=True, min_count=1
        )
        values = (weighted_sum / weight_sum).where(weight_sum > 0)
    elif query.aggregation_method == "min":
        values = data["polaris_min"].min(dimension, skipna=True)
    else:
        values = data["polaris_max"].max(dimension, skipna=True)
    values = values.rename(query.variable)
    values.attrs = data[query.variable].attrs.copy()
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
    matches = values.notnull() & operations[query.predicate](
        values, query.filter_value
    )
    result = data.copy()
    result["matches"] = matches
    result["matches"].attrs = {
        "long_name": f"{query.variable} {query.predicate} {query.filter_value}",
        "predicate": query.predicate,
        "filter_value": query.filter_value,
    }
    return result


def _with_cell_topology(result: xr.Dataset, source: xr.Dataset) -> xr.Dataset:
    """Restore cell coordinates whose vertex dimension is not on the value."""
    if "cell" not in result.dims:
        return result
    for name, coordinate in source.coords.items():
        if name in result.coords or "timestamp" in coordinate.dims:
            continue
        if set(coordinate.dims).issubset({"cell", "vertex"}):
            result = result.assign_coords({name: coordinate})
        elif not coordinate.dims:
            result = result.assign_coords({name: coordinate})
    return result


def _compute_result(data: xr.Dataset, query: Query) -> xr.Dataset:
    if query.function == "get-data":
        result = _requested_values(data, query).to_dataset()
        return _with_cell_topology(result, data)
    if query.function == "timeseries":
        return _collapse_data(data, query, "cell")
    if query.function == "heatmap":
        return _with_cell_topology(_collapse_data(data, query, "timestamp"), data)
    if query.function == "find-time":
        return _apply_predicate(_collapse_data(data, query, "cell"), query)
    if query.function == "find-area":
        result = _collapse_data(data, query, "timestamp")
        return _apply_predicate(_with_cell_topology(result, data), query)
    raise ValueError(f"Unsupported function: {query.function!r}")


def _unique_metadata_values(
    records: tuple[dict[str, Any], ...],
    name: str,
) -> tuple[Any, ...]:
    values = {}
    for record in records:
        value = record.get(name)
        values.setdefault(json.dumps(value, sort_keys=True), value)
    return tuple(values.values())


def _source_info(
    group: MatchingBlockGroup,
    records: tuple[dict[str, Any], ...],
) -> SourceInfo:
    return SourceInfo(
        repository=group.repository,
        dataset=group.dataset,
        variable=group.variable,
        additional_parameters=group.additional_parameters,
        native_temporal_resolutions=_unique_metadata_values(
            records, "native_temporal_resolution"
        ),
        native_spatial_resolutions=_unique_metadata_values(
            records, "native_spatial_resolution"
        ),
        block_ids=tuple(record["block_id"] for record in records),
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
            "block_ids": json.dumps(
                [record["block_id"] for record in records]
            ),
        }
    )
    return result


def _write_result(data: xr.Dataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".partial")
    try:
        data.to_netcdf(temporary_path)
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def execute_query(
    query: Query | Mapping[str, Any],
    settings: Settings | None = None,
    output_dir: Path | None = None,
) -> QueryResult:
    """Plan and execute one query, returning a NetCDF result per group."""
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
        source_data, used_records, reading_warnings = _get_data(plan, group)
        warnings.extend(reading_warnings)
        if source_data is None:
            warning = (
                f"No cells could be read for {group.repository}/{group.dataset}/"
                f"{group.variable}."
            )
            warnings.append(warning)
            continue
        group_id = _group_id(group)
        result_data = _decorate_result(
            _compute_result(source_data, plan.query),
            plan,
            group,
            query_id,
            group_id,
            used_records,
        )
        path = output_dir / query_id / plan.query.function / f"{group_id}.nc"
        _write_result(result_data, path)
        source = _source_info(group, used_records)
        results.append(
            GroupResult(
                group_id=group_id,
                data=result_data,
                file_path=path,
                source=source,
                units=result_data[plan.query.variable].attrs.get("units"),
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
