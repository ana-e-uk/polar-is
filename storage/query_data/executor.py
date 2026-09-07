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


def _block_to_cells(
    data: xr.Dataset,
    query: Query,
    bucket_id: str,
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

    names = [query.variable, *AGGREGATE_STATISTICS]
    cells = data[names].stack(cell=("y", "x")).isel(cell=cell_indices)
    latitude, longitude = xr.broadcast(data["latitude"], data["longitude"])
    latitude = latitude.transpose("y", "x").stack(cell=("y", "x"))
    longitude = (longitude % 360).transpose("y", "x").stack(cell=("y", "x"))
    latitude_values = latitude.isel(cell=cell_indices).values
    longitude_values = longitude.isel(cell=cell_indices).values
    cell_keys = np.asarray(
        [
            f"{float(lat):.12g},{float(lon):.12g}"
            for lat, lon in zip(latitude_values, longitude_values)
        ],
        dtype=str,
    )
    cells = cells.reset_index("cell", drop=True).assign_coords(
        cell=cell_keys,
        latitude=("cell", latitude_values),
        longitude=("cell", longitude_values),
        bucket_id=("cell", np.full(cell_keys.size, bucket_id, dtype=str)),
    )
    for name in names:
        cells[name] = cells[name].transpose("timestamp", "cell")
    return cells.load()


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
            cells = _block_to_cells(data, plan.query, record["bucket_id"])
        if cells is not None:
            blocks.append(cells)
            used_records.append(record)
        else:
            warnings.append(
                f"Block {record['block_id']} had no cells after coordinate cropping."
            )
    if not blocks:
        return None, tuple(used_records), tuple(warnings)

    combined = xr.combine_by_coords(
        blocks,
        combine_attrs="override",
        data_vars="all",
        coords="minimal",
    ).sortby("timestamp")
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


def _compute_result(data: xr.Dataset, query: Query) -> xr.Dataset:
    if query.function == "get-data":
        return _requested_values(data, query).to_dataset()
    if query.function == "timeseries":
        return _collapse_data(data, query, "cell")
    if query.function == "heatmap":
        return _collapse_data(data, query, "timestamp")
    if query.function == "find-time":
        return _apply_predicate(_collapse_data(data, query, "cell"), query)
    if query.function == "find-area":
        return _apply_predicate(_collapse_data(data, query, "timestamp"), query)
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
