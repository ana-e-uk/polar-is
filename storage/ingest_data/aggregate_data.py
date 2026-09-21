"""Create the configured temporal/spatial hierarchy from native datasets.

Every product is derived from the standardized native dataset and written as
time partitions through one shared index. Spatial factors are never chained.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
import xarray as xr

from polaris.config import get_settings
from storage.bucket_lookup import ensure_bucket_lookup
from storage.ingest_data.product_partitions import (
    _preserve_compression,
    timestamp_string,
    write_product_partitions,
)
from storage.ingest_data.standardize import read_metadata
from storage.grid_topology import canonical_grid, ensure_grid_catalog


_RESOLUTION_ALIASES = {
    "H": "1H",
    "1H": "1H",
    "3H": "3H",
    "W": "1W",
    "1W": "1W",
    "7D": "1W",
    "D": "1D",
    "1D": "1D",
    "M": "1MS",
    "1M": "1MS",
    "MS": "1MS",
    "1MS": "1MS",
    "Y": "1YS",
    "1Y": "1YS",
    "YS": "1YS",
    "1YS": "1YS",
}
_RESOLUTION_ORDER = {
    "1H": 0,
    "3H": 1,
    "1D": 2,
    "1W": 3,
    "1MS": 4,
    "1YS": 5,
}
_XR_FREQUENCY = {
    "1H": "1h",
    "3H": "3h",
    "1D": "1D",
    "1MS": "1MS",
    "1YS": "1YS",
}

AGGREGATE_STATISTICS = (
    "polaris_weighted_sum",
    "polaris_weight_sum",
    "polaris_min",
    "polaris_max",
)

_PRODUCT_RESOLUTIONS = {
    "Hour": "1H",
    "Day": "1D",
    "Month": "1MS",
    "Year": "1YS",
}


@dataclass(frozen=True)
class ProductSpec:
    """One product selected by the ingestion policy."""

    time_unit: str
    coarseness_factor: int


def product_policy(native_resolution: str) -> tuple[ProductSpec, ...]:
    """Return the complete reduced product set for one source cadence.

    Source is retained only at its native spatial resolution. Temporal
    products are strictly coarser than Source, and the factor-2 spatial product
    is reserved for monthly and yearly data.
    """
    native = normalize_temporal_resolution(native_resolution)
    if native == "1W":
        raise ValueError(
            "Weekly source data is unsupported until calendar-boundary "
            "weighting is defined"
        )

    products = [ProductSpec("Source", 1)]
    for time_unit, target in _PRODUCT_RESOLUTIONS.items():
        if _RESOLUTION_ORDER[target] <= _RESOLUTION_ORDER[native]:
            continue
        products.append(ProductSpec(time_unit, 1))
        if time_unit in {"Month", "Year"}:
            products.append(ProductSpec(time_unit, 2))
    return tuple(products)


def combined_product_policy() -> tuple[ProductSpec, ...]:
    """Return the fixed products materialized for the daily Combined dataset."""
    return (
        ProductSpec("Day", 1),
        ProductSpec("Month", 1),
        ProductSpec("Month", 2),
        ProductSpec("Year", 1),
        ProductSpec("Year", 2),
    )


def normalize_temporal_resolution(value: str) -> str:
    try:
        return _RESOLUTION_ALIASES[str(value).upper()]
    except KeyError as error:
        raise ValueError(f"Unsupported temporal resolution: {value!r}") from error


def infer_native_temporal_resolution(
    timestamp: xr.DataArray,
    declared_resolution: str,
) -> str:
    """Infer supported native cadence from standardized timestamps."""
    index = pd.DatetimeIndex(timestamp.values)
    if not index.is_monotonic_increasing or not index.is_unique:
        raise ValueError("timestamp must be strictly increasing and unique")
    if len(index) < 2:
        return normalize_temporal_resolution(declared_resolution)
    nanoseconds = index.to_numpy(dtype="datetime64[ns]").astype(np.int64)
    differences = np.diff(nanoseconds)
    if np.all(differences == pd.Timedelta(hours=1).value):
        return "1H"
    if np.all(differences == pd.Timedelta(hours=3).value):
        return "3H"
    if np.all(differences == pd.Timedelta(days=1).value):
        return "1D"
    if np.all(differences == pd.Timedelta(days=7).value):
        return "1W"
    if all(
        current == previous + pd.offsets.MonthBegin(1)
        for previous, current in zip(index[:-1], index[1:])
    ):
        return "1MS"
    if all(
        current == previous + pd.offsets.YearBegin(1)
        for previous, current in zip(index[:-1], index[1:])
    ):
        return "1YS"
    raise ValueError("Could not infer a supported uniform native time interval")


def _resample_reduce(
    array: xr.DataArray,
    frequency: str,
    method: str,
) -> xr.DataArray:
    resampler = array.resample(timestamp=_XR_FREQUENCY[frequency])
    try:
        reducer = getattr(resampler, method)
    except AttributeError as error:
        raise ValueError(f"Unsupported temporal reducer: {method!r}") from error
    if method == "sum":
        result = reducer(skipna=True, keep_attrs=True)
        return result.where(
            array.resample(timestamp=_XR_FREQUENCY[frequency]).count() > 0
        )
    return reducer(skipna=True, keep_attrs=True)


def _complete_period_labels(
    timestamp: xr.DataArray,
    native_resolution: str,
    target_resolution: str,
) -> list[np.datetime64]:
    """Return labels whose complete native timestamp sequence is present."""
    index = pd.DatetimeIndex(timestamp.values)
    if not index.is_monotonic_increasing or not index.is_unique:
        raise ValueError("timestamp must be strictly increasing and unique")
    target_frequency = _XR_FREQUENCY[target_resolution]
    native_frequency = _XR_FREQUENCY[native_resolution]
    labels = pd.DatetimeIndex(
        xr.DataArray(
            np.ones(index.size, dtype=np.int8),
            coords={"timestamp": index},
            dims="timestamp",
        )
        .resample(timestamp=target_frequency)
        .sum()["timestamp"]
        .values
    )
    target_offset = pd.tseries.frequencies.to_offset(target_frequency)
    valid = []
    for label in labels:
        next_label = label + target_offset
        actual = index[(index >= label) & (index < next_label)]
        expected = pd.date_range(
            label,
            next_label,
            freq=native_frequency,
            inclusive="left",
        )
        # Some products timestamp interval midpoints (for example 01:30 for a
        # three-hour interval). Uniform cadence is validated before this
        # function; a full interval count therefore establishes completeness
        # without requiring boundary-aligned timestamp labels.
        if len(actual) == len(expected):
            valid.append(label.to_datetime64())
    return valid


def temporally_aggregate(
    data: xr.Dataset,
    variable: str,
    native_resolution: str,
    target_resolution: str,
    method: str,
) -> xr.Dataset:
    """Aggregate time and discard target periods without full native coverage."""
    native = normalize_temporal_resolution(native_resolution)
    target = normalize_temporal_resolution(target_resolution)
    if _RESOLUTION_ORDER[target] < _RESOLUTION_ORDER[native]:
        raise ValueError(f"Cannot aggregate {native} data to finer {target} data")
    if target == native:
        return data
    if "timestamp" not in data.dims:
        raise ValueError("Dataset must have a timestamp dimension")

    valid_labels = _complete_period_labels(data["timestamp"], native, target)
    scientific = _resample_reduce(data[variable], target, method)
    result = scientific.to_dataset(name=variable)
    has_statistics = all(name in data for name in AGGREGATE_STATISTICS)
    for name, array in data.data_vars.items():
        if name == variable or name in AGGREGATE_STATISTICS:
            continue
        if "timestamp" in array.dims:
            auxiliary = array.resample(timestamp=_XR_FREQUENCY[target])
            if name == "source_count":
                result[name] = auxiliary.max(skipna=True, keep_attrs=True)
            else:
                result[name] = auxiliary.first(keep_attrs=True)
        else:
            result[name] = array
    if has_statistics:
        result["polaris_min"] = data["polaris_min"].resample(
            timestamp=_XR_FREQUENCY[target]
        ).min(skipna=True)
        result["polaris_max"] = data["polaris_max"].resample(
            timestamp=_XR_FREQUENCY[target]
        ).max(skipna=True)
        if method == "mean":
            result["polaris_weighted_sum"] = data[
                "polaris_weighted_sum"
            ].resample(timestamp=_XR_FREQUENCY[target]).sum()
            result["polaris_weight_sum"] = data[
                "polaris_weight_sum"
            ].resample(timestamp=_XR_FREQUENCY[target]).sum()
        else:
            valid = scientific.notnull()
            result["polaris_weighted_sum"] = (
                scientific * data["cell_area"]
            ).where(valid, 0)
            result["polaris_weight_sum"] = data["cell_area"].where(
                valid, 0
            )
    for name, coordinate in data.coords.items():
        if name == "timestamp" or name in result.coords:
            continue
        if "timestamp" in coordinate.dims:
            result = result.assign_coords(
                {
                    name: coordinate.resample(
                        timestamp=_XR_FREQUENCY[target]
                    ).first(keep_attrs=True)
                }
            )
        else:
            result = result.assign_coords({name: coordinate})
    result = result.sel(timestamp=valid_labels)
    for name in result.data_vars:
        if name in data.data_vars:
            _preserve_compression(data[name], result[name])
    result.attrs = data.attrs.copy()
    return result


def _coarsen_reduce(
    array: xr.DataArray,
    factor: int,
    method: str,
) -> xr.DataArray:
    windows = {
        dimension: factor
        for dimension in ("y", "x")
        if dimension in array.dims
    }
    if not windows:
        return array
    if method == "first":
        # The first element of windows [0:factor], [factor:2*factor], ...
        # is exactly the strided selection 0, factor, 2*factor, ... . This
        # preserves all non-spatial dimensions and works for NumPy, Dask,
        # numeric, and non-numeric arrays without xarray's reduce callback
        # having to interpret its temporary window axes.
        return array.isel(
            {
                dimension: slice(0, None, factor)
                for dimension in windows
            }
        )
    coarsener = array.coarsen(windows, boundary="pad")
    try:
        reducer = getattr(coarsener, method)
    except AttributeError as error:
        raise ValueError(f"Unsupported spatial reducer: {method!r}") from error
    if method == "sum":
        result = reducer(skipna=True, keep_attrs=True)
        return result.where(array.coarsen(windows, boundary="pad").count() > 0)
    return reducer(skipna=True, keep_attrs=True)


def add_aggregate_statistics(
    data: xr.Dataset,
    variable: str,
    cell_area: xr.DataArray | None = None,
) -> xr.Dataset:
    """Add statistics used to combine spatial aggregate values correctly."""
    result = data.copy()
    if cell_area is None and "cell_area" in result:
        cell_area = result["cell_area"]
    if cell_area is None:
        latitude, _ = xr.broadcast(result["latitude"], result["longitude"])
        cell_area = np.cos(np.deg2rad(latitude)).clip(min=0)
        cell_area = cell_area.transpose("y", "x")
        cell_area.name = "cell_area"
        cell_area.attrs = {
            "long_name": "relative grid-cell area",
            "units": "relative",
        }

    values = result[variable]
    valid = values.notnull()
    result["polaris_weighted_sum"] = (values * cell_area).where(valid, 0)
    result["polaris_weight_sum"] = cell_area.where(valid, 0).transpose(
        *values.dims
    )
    result["polaris_min"] = values
    result["polaris_max"] = values
    for name in ("polaris_weighted_sum", "polaris_min", "polaris_max"):
        result[name].attrs = values.attrs.copy()
    result["polaris_weight_sum"].attrs = {
        "long_name": "sum of valid spatial weights",
        "units": cell_area.attrs.get("units", "1"),
    }
    return result


def _circularly_coarsen_longitude(
    longitude: xr.DataArray,
    factor: int,
) -> xr.DataArray:
    radians = np.deg2rad(longitude)
    sine = _coarsen_reduce(np.sin(radians), factor, "mean")
    cosine = _coarsen_reduce(np.cos(radians), factor, "mean")
    result = np.rad2deg(np.arctan2(sine, cosine)) % 360
    result.attrs = longitude.attrs.copy()
    result.name = longitude.name
    return result


def _auxiliary_spatial_method(name: str, array: xr.DataArray) -> str:
    if name == "source_count":
        return "max"
    standard_name = str(array.attrs.get("standard_name", "")).lower()
    if standard_name == "cell_area" or "cell_area" in name.lower():
        return "sum"
    if "flag_values" in array.attrs or "flag_masks" in array.attrs:
        return "first"
    return "mean" if np.issubdtype(array.dtype, np.number) else "first"


def _coarsen_axis_bounds(
    bounds: xr.DataArray,
    dimension: str,
    factor: int,
) -> xr.DataArray:
    """Keep the outside edges of each coarsened rectilinear cell."""
    lower = _coarsen_reduce(bounds.isel(bounds=0), factor, "min")
    upper = _coarsen_reduce(bounds.isel(bounds=1), factor, "max")
    result = xr.concat([lower, upper], dim="bounds").transpose(dimension, "bounds")
    result = result.assign_coords(bounds=[0, 1])
    result.attrs = bounds.attrs.copy()
    return result


def spatially_aggregate(
    data: xr.Dataset,
    variable: str,
    factor: int,
    method: str,
) -> xr.Dataset:
    """Coarsen native y/x cells without reprojection, using padded edges."""
    if factor == 1:
        return data
    if factor < 1:
        raise ValueError("Spatial coarsening factor must be positive")

    has_statistics = all(name in data for name in AGGREGATE_STATISTICS)
    if method == "mean" and has_statistics:
        weighted_sum = _coarsen_reduce(
            data["polaris_weighted_sum"], factor, "sum"
        )
        weight_sum = _coarsen_reduce(
            data["polaris_weight_sum"], factor, "sum"
        )
        scientific = (weighted_sum / weight_sum).where(weight_sum > 0)
        scientific.attrs = data[variable].attrs.copy()
    else:
        scientific = _coarsen_reduce(data[variable], factor, method)
    result = scientific.to_dataset(name=variable)
    for name, array in data.data_vars.items():
        if name == variable or name in AGGREGATE_STATISTICS:
            continue
        if name in {"latitude_bounds", "longitude_bounds"}:
            continue
        if not ({"y", "x"} & set(array.dims)):
            result[name] = array
            continue
        auxiliary_method = _auxiliary_spatial_method(name, array)
        result[name] = _coarsen_reduce(
            array,
            factor,
            auxiliary_method,
        )
        if name == "source_count":
            result[name] = result[name].astype(array.dtype)

    if has_statistics:
        result["polaris_weighted_sum"] = _coarsen_reduce(
            data["polaris_weighted_sum"], factor, "sum"
        )
        result["polaris_weight_sum"] = _coarsen_reduce(
            data["polaris_weight_sum"], factor, "sum"
        )
        result["polaris_min"] = _coarsen_reduce(
            data["polaris_min"], factor, "min"
        )
        result["polaris_max"] = _coarsen_reduce(
            data["polaris_max"], factor, "max"
        )

    if "latitude" in data.coords:
        result = result.assign_coords(
            latitude=_coarsen_reduce(data["latitude"], factor, "mean")
        )
    if "longitude" in data.coords:
        result = result.assign_coords(
            longitude=_circularly_coarsen_longitude(
                data["longitude"], factor
            )
        )
    if "latitude_bounds" in data:
        result["latitude_bounds"] = _coarsen_axis_bounds(
            data["latitude_bounds"], "y", factor
        )
    if "longitude_bounds" in data:
        result["longitude_bounds"] = _coarsen_axis_bounds(
            data["longitude_bounds"], "x", factor
        )
    for name, coordinate in data.coords.items():
        if (
            name in {"latitude", "longitude"}
            or name in result.coords
        ):
            continue
        if {"y", "x"} & set(coordinate.dims):
            method_for_coordinate = (
                "mean"
                if np.issubdtype(coordinate.dtype, np.number)
                else "first"
            )
            result = result.assign_coords(
                {name: _coarsen_reduce(coordinate, factor, method_for_coordinate)}
            )
        else:
            result = result.assign_coords({name: coordinate})
    for name in result.data_vars:
        if name in data.data_vars:
            _preserve_compression(data[name], result[name])
    result.attrs = data.attrs.copy()
    result.attrs["polaris_coarseness_factor"] = factor
    return result


def _scaled_spatial_resolution(value, factor: int):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value * factor
    if isinstance(value, list):
        return [item * factor for item in value]
    return value


def _product_metadata(
    record: dict,
    data: xr.Dataset,
    target_resolution: str,
    factor: int,
    temporal_method: str | None,
    spatial_method: str | None,
    native_temporal: str | None = None,
) -> dict:
    native_temporal = native_temporal or infer_native_temporal_resolution(
        data["timestamp"], record["temporal_resolution"]
    )
    native_spatial = record.get("spatial_resolution")
    timestamps = data["timestamp"]
    return {
        "product_type": (
            "native"
            if target_resolution == native_temporal and factor == 1
            else "aggregate"
        ),
        "native_temporal_resolution": native_temporal,
        "temporal_resolution": target_resolution,
        "native_spatial_resolution": native_spatial,
        "spatial_resolution": _scaled_spatial_resolution(
            native_spatial, factor
        ),
        "coarseness_factor": factor,
        "temporal_aggregation_method": temporal_method,
        "spatial_aggregation_method": spatial_method,
        "aggregation_order": "temporal_then_spatial",
        "time_start": timestamp_string(timestamps.values[0]),
        "time_end": timestamp_string(timestamps.values[-1]),
    }


def aggregate_record(
    record: dict,
    *,
    settings=None,
) -> list[dict]:
    """Generate every eligible capacity/time product for one native record."""
    settings = settings or get_settings()
    variable = record["variable"]
    try:
        methods = settings.aggregation_methods[variable]
        temporal_method = methods["temporal"]
        spatial_method = methods["spatial"]
    except KeyError as error:
        raise ValueError(
            f"Missing aggregation methods for {variable!r}"
        ) from error
    written = []
    with xr.open_dataset(record["file_path"]) as native:
        native_resolution = infer_native_temporal_resolution(
            native["timestamp"], record["temporal_resolution"]
        )
        is_combined = (
            record.get("repository") == settings.combined_dataset.get("repository")
            and record.get("dataset") == settings.combined_dataset.get("dataset")
        )
        products = combined_product_policy() if is_combined else product_policy(
            native_resolution
        )
        grid_record = ensure_grid_catalog(
            native,
            record.get("grid_type"),
            settings=settings,
        )
        grid = canonical_grid(native, record.get("grid_type"))
        ensure_bucket_lookup(grid_record, grid, settings=settings)
        native_with_statistics = add_aggregate_statistics(
            native,
            variable,
            grid["cell_area"].reset_coords(drop=True),
        )
        temporal_products = {}
        for product_spec in products:
            if product_spec.time_unit == "Source":
                target = native_resolution
                temporal_data = native
            elif is_combined and product_spec.time_unit == "Day":
                target = native_resolution
                temporal_data = native_with_statistics
            else:
                target = _PRODUCT_RESOLUTIONS[product_spec.time_unit]
                if target not in temporal_products:
                    temporal_products[target] = temporally_aggregate(
                        native_with_statistics,
                        variable,
                        native_resolution,
                        target,
                        temporal_method,
                    )
                temporal_data = temporal_products[target]
            if temporal_data.sizes.get("timestamp", 0) == 0:
                continue
            factor = product_spec.coarseness_factor
            product = spatially_aggregate(
                temporal_data,
                variable,
                factor,
                spatial_method,
            )
            written.extend(
                write_product_partitions(
                    product,
                    record,
                    grid_id=grid_record.grid_id,
                    grid_shape=(grid_record.shape_y, grid_record.shape_x),
                    time_unit=product_spec.time_unit,
                    temporal_resolution=target,
                    coarseness_factor=factor,
                    settings=settings,
                )
            )
    return written


def aggregate_records(
    records: list[dict],
    *,
    settings=None,
    delete_sources: bool = False,
) -> list[dict]:
    """Aggregate all records; optionally remove sources after total success."""
    settings = settings or get_settings()
    written = []
    for record in records:
        written.extend(aggregate_record(record, settings=settings))
    if delete_sources:
        for record in records:
            Path(record["file_path"]).unlink()
    return written


def _clear_metadata_atomically(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".partial",
    )
    os.close(descriptor)
    Path(temporary_name).replace(path)


def aggregate_standardized_metadata() -> list[dict]:
    """Run the hierarchy and consume its standardized inputs on success."""
    settings = get_settings()
    records = read_metadata(settings.standardized_data_)
    from storage.ingest_data.combine_data import build_combined_records

    combined_records = build_combined_records(records, settings=settings)
    all_records = [*records, *combined_records]
    written = aggregate_records(all_records, settings=settings, delete_sources=False)
    _clear_metadata_atomically(settings.standardized_data_)
    for record in all_records:
        Path(record["file_path"]).unlink()
    return written


if __name__ == "__main__":
    aggregate_standardized_metadata()
