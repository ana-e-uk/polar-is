"""Build daily equal-weight Combined products on the canonical ERA5 grid.

The source datasets remain on their native grids until after their daily mean
and per-cell coverage threshold have been calculated.  Spatial operators and
their grid geometry are cached independently of the source values.
"""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import xarray as xr

from polaris.config import get_settings
from storage.grid_topology import (
    _axis_edges,
    ensure_grid_catalog,
    grid_cell_area,
)
from storage.ingest_data.aggregate_data import infer_native_temporal_resolution
from storage.ingest_data.standardize import unique_output_path


_EXPECTED_DAILY_SAMPLES = {"1H": 24, "3H": 8, "1D": 1}


def daily_mean_with_coverage(
    values: xr.DataArray,
    native_resolution: str,
    minimum_coverage: float,
) -> xr.DataArray:
    """Return daily means only where enough native samples are valid."""
    if not 0 < minimum_coverage <= 1:
        raise ValueError("minimum_daily_coverage must be in the interval (0, 1]")
    try:
        expected = _EXPECTED_DAILY_SAMPLES[native_resolution]
    except KeyError as error:
        raise ValueError(
            f"Cannot create daily values from {native_resolution!r} data"
        ) from error
    required = math.ceil(expected * minimum_coverage)
    resampler = values.resample(timestamp="1D")
    result = resampler.mean(skipna=True, keep_attrs=True)
    valid_count = resampler.count()
    result = result.where(valid_count >= required)
    result.attrs = values.attrs.copy()
    result.attrs.update(
        {
            "polaris_daily_expected_samples": expected,
            "polaris_daily_required_samples": required,
            "polaris_minimum_daily_coverage": minimum_coverage,
        }
    )
    return result


def combine_daily_arrays(
    arrays: Iterable[xr.DataArray],
    weights: Iterable[float],
) -> tuple[xr.DataArray, xr.DataArray]:
    """Combine aligned fields and return their mean and contributor count."""
    arrays = list(arrays)
    weights = list(weights)
    if not arrays:
        raise ValueError("At least one daily source array is required")
    if len(arrays) != len(weights):
        raise ValueError("Every daily source array must have one weight")
    if any(not np.isfinite(weight) or weight <= 0 for weight in weights):
        raise ValueError("Combined dataset weights must be finite and positive")

    aligned = xr.align(*arrays, join="outer", copy=False)
    numerator = xr.zeros_like(aligned[0], dtype=np.float64)
    denominator = xr.zeros_like(aligned[0], dtype=np.float64)
    source_count = xr.zeros_like(aligned[0], dtype=np.int16)
    for values, weight in zip(aligned, weights):
        valid = values.notnull()
        numerator = numerator + values.fillna(0) * weight
        denominator = denominator + valid.astype(np.float64) * weight
        source_count = source_count + valid.astype(np.int16)
    combined = (numerator / denominator).where(denominator > 0)
    combined.attrs = arrays[0].attrs.copy()
    source_count.name = "source_count"
    source_count.attrs = {
        "long_name": "number of source datasets contributing to Combined",
        "units": "1",
    }
    return combined, source_count


def _projected_corners(data: xr.Dataset) -> tuple[np.ndarray, np.ndarray] | None:
    if "projection_x" not in data.coords or "projection_y" not in data.coords:
        return None
    from storage.grid_topology import transformer_from_grid_mapping

    transformer = transformer_from_grid_mapping(data)
    if transformer is None:
        return None
    x_edges = _axis_edges(data, "projection_x")
    y_edges = _axis_edges(data, "projection_y")
    xx, yy = np.meshgrid(x_edges, y_edges)
    longitude, latitude = transformer.transform(xx, yy)
    return np.asarray(latitude), np.asarray(longitude) % 360


def xesmf_grid(data: xr.Dataset) -> xr.Dataset:
    """Return an xESMF grid plus centers, corners, and retained cell areas."""
    latitude = data["latitude"]
    longitude = data["longitude"]
    grid = xr.Dataset(
        coords={
            "lat": (latitude.dims, latitude.data, latitude.attrs),
            "lon": (longitude.dims, longitude.data, longitude.attrs),
        }
    )
    if latitude.ndim == 1 and longitude.ndim == 1:
        grid = grid.assign_coords(
            lat_b=("y_b", _axis_edges(data, "latitude")),
            lon_b=("x_b", _axis_edges(data, "longitude")),
        )
    else:
        corners = _projected_corners(data)
        if corners is not None:
            grid = grid.assign_coords(
                lat_b=(("y_b", "x_b"), corners[0]),
                lon_b=(("y_b", "x_b"), corners[1]),
            )
    grid["cell_area"] = grid_cell_area(data)
    grid["domain_mask"] = xr.DataArray(
        np.ones((data.sizes["y"], data.sizes["x"]), dtype=np.int8),
        dims=("y", "x"),
        attrs={
            "long_name": "static source-grid domain mask",
            "flag_values": [0, 1],
            "flag_meanings": "outside_domain inside_domain",
        },
    )
    if "crs" in data:
        for name in ("crs_wkt", "spatial_ref", "grid_mapping_name"):
            if name in data["crs"].attrs:
                grid.attrs[name] = data["crs"].attrs[name]
    return grid


def _grid_hash(grid: xr.Dataset) -> str:
    digest = hashlib.blake2b(digest_size=16)
    for name in ("lat", "lon", "lat_b", "lon_b"):
        if name not in grid:
            continue
        values = np.ascontiguousarray(grid[name].values, dtype=np.float64)
        digest.update(name.encode())
        digest.update(str(values.shape).encode())
        digest.update(values.tobytes())
    digest.update(
        json.dumps(grid.attrs, sort_keys=True, default=str).encode()
    )
    return digest.hexdigest()


def _write_netcdf_once(data: xr.Dataset, path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial.nc")
    try:
        data.to_netcdf(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_xesmf():
    try:
        import xesmf as xe
    except ImportError as error:
        raise RuntimeError(
            "Combined spatial remapping requires xESMF and ESMF/ESMPy. "
            "Run this pipeline from the project's xESMF-capable environment."
        ) from error
    return xe


def _is_periodic(grid: xr.Dataset) -> bool:
    if grid["lon"].ndim != 1 or "lon_b" not in grid:
        return False
    edges = np.asarray(grid["lon_b"].values)
    return bool(abs(edges[-1] - edges[0]) >= 359)


def regrid_daily_to_target(
    values: xr.DataArray,
    source: xr.Dataset,
    target: xr.Dataset,
    cache_dir: Path,
    method: str,
) -> xr.DataArray:
    """Apply one cached xESMF operator to a daily source field."""
    source_grid = xesmf_grid(source)
    target_grid = xesmf_grid(target)
    source_hash = _grid_hash(source_grid)
    target_hash = _grid_hash(target_grid)
    weights_dir = cache_dir / "weights"

    operator_id = f"{source_hash}__to__{target_hash}__{method}"
    weights_path = weights_dir / f"{operator_id}.nc"
    weights_dir.mkdir(parents=True, exist_ok=True)
    xe = _load_xesmf()
    common_kwargs = {
        "periodic": _is_periodic(source_grid),
        "unmapped_to_nan": True,
        "ignore_degenerate": True,
    }
    if weights_path.exists():
        regridder = xe.Regridder(
            source_grid,
            target_grid,
            method,
            filename=str(weights_path),
            reuse_weights=True,
            **common_kwargs,
        )
    else:
        temporary_weights = weights_path.with_name(
            f".{weights_path.stem}.partial.nc"
        )
        try:
            regridder = xe.Regridder(
                source_grid,
                target_grid,
                method,
                filename=str(temporary_weights),
                **common_kwargs,
            )
            temporary_weights.replace(weights_path)
        finally:
            temporary_weights.unlink(missing_ok=True)
    _write_json(
        weights_dir / f"{operator_id}.json",
        {
            "method": method,
            "periodic_source": _is_periodic(source_grid),
            "source_grid_hash": source_hash,
            "target_grid_hash": target_hash,
            "weight_file": weights_path.name,
            "xesmf_version": getattr(xe, "__version__", None),
        },
    )
    remapped = regridder(values, keep_attrs=True, skipna=True, na_thres=1.0)
    # xESMF preserves auxiliary source coordinates. A projected source can
    # therefore leave its scalar CRS on an otherwise rectilinear target field.
    # Reconstruct the array with dimension coordinates only, then attach the
    # canonical target grid explicitly.
    dimension_coordinates = {
        dimension: remapped[dimension]
        for dimension in remapped.dims
        if dimension not in {"y", "x"} and dimension in remapped.coords
    }
    result = xr.DataArray(
        remapped.data,
        dims=remapped.dims,
        coords=dimension_coordinates,
        name=values.name,
        attrs=remapped.attrs.copy(),
    ).assign_coords(
        latitude=(
            target["latitude"].dims,
            target["latitude"].data,
            target["latitude"].attrs,
        ),
        longitude=(
            target["longitude"].dims,
            target["longitude"].data,
            target["longitude"].attrs,
        ),
    )
    return result


def _source_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    parameters = record.get("additional_parameters", record.get("additional_params")) or {}
    return (
        record["repository"],
        record["dataset"],
        record["variable"],
        json.dumps(parameters, sort_keys=True, separators=(",", ":")),
    )


def _weight_for(record: dict[str, Any], configuration: dict[str, Any]) -> float:
    key = f"{record['repository']}/{record['dataset']}"
    return float(configuration.get("weights", {}).get(key, configuration["default_weight"]))


def _open_source_group(
    stack: ExitStack,
    records: list[dict[str, Any]],
) -> xr.Dataset:
    datasets = [stack.enter_context(xr.open_dataset(record["file_path"])) for record in records]
    if len(datasets) == 1:
        return datasets[0]
    return xr.combine_by_coords(datasets, combine_attrs="override").sortby("timestamp")


def _target_template(target: xr.Dataset) -> xr.Dataset:
    template = xr.Dataset(
        coords={
            "latitude": (
                target["latitude"].dims,
                target["latitude"].data,
                target["latitude"].attrs,
            ),
            "longitude": (
                target["longitude"].dims,
                target["longitude"].data,
                target["longitude"].attrs,
            ),
        },
        attrs={"polaris_grid_type": "rectilinear"},
    )
    for name in ("latitude_bounds", "longitude_bounds"):
        if name in target:
            template[name] = target[name]
    return template


def build_combined_records(
    records: list[dict[str, Any]],
    *,
    settings=None,
    regrid: Callable[..., xr.DataArray] = regrid_daily_to_target,
) -> list[dict[str, Any]]:
    """Create standardized daily Combined files, one per configured variable."""
    settings = settings or get_settings()
    configuration = settings.combined_dataset
    if not configuration.get("enabled", False) or not records:
        return []
    source_records = [
        record
        for record in records
        if not (
            record.get("repository") == configuration["repository"]
            and record.get("dataset") == configuration["dataset"]
        )
    ]
    target_records = [
        record
        for record in source_records
        if record.get("repository") == configuration["target_repository"]
        and record.get("dataset") == configuration["target_dataset"]
    ]
    if not target_records:
        raise ValueError(
            "Combined requires a standardized canonical ERA5 target-grid record"
        )

    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for record in source_records:
        if record.get("variable") not in configuration["variables"]:
            continue
        grouped.setdefault(_source_key(record), []).append(record)

    output_records = []
    with ExitStack() as stack:
        target_data = stack.enter_context(xr.open_dataset(target_records[0]["file_path"]))
        if target_data["latitude"].ndim != 1 or target_data["longitude"].ndim != 1:
            raise ValueError("The Combined target ERA5 grid must be rectilinear")
        target_template = _target_template(target_data)
        ensure_grid_catalog(target_data, "rectilinear", settings=settings)

        by_variable: dict[str, list[list[dict[str, Any]]]] = {}
        for key, group in grouped.items():
            by_variable.setdefault(key[2], []).append(group)

        for variable, source_groups in by_variable.items():
            remapped = []
            weights = []
            provenance = []
            units_marker = object()
            units: Any = units_marker
            attrs = None
            for group in source_groups:
                source = _open_source_group(stack, group)
                ensure_grid_catalog(
                    source,
                    group[0].get("grid_type"),
                    settings=settings,
                )
                native_resolution = infer_native_temporal_resolution(
                    source["timestamp"], group[0]["temporal_resolution"]
                )
                daily = daily_mean_with_coverage(
                    source[variable],
                    native_resolution,
                    float(configuration["minimum_daily_coverage"]),
                )
                source_units = daily.attrs.get("units")
                if units is units_marker:
                    units = source_units
                    attrs = source[variable].attrs.copy()
                elif source_units != units:
                    raise ValueError(
                        f"Combined {variable!r} has incompatible units: "
                        f"{units!r} and {source_units!r}"
                    )
                remapped.append(
                    regrid(
                        daily,
                        source,
                        target_data,
                        Path(configuration["cache_dir"]),
                        configuration["regridding_method"],
                    )
                )
                weights.append(_weight_for(group[0], configuration))
                provenance.append(
                    {
                        "repository": group[0]["repository"],
                        "dataset": group[0]["dataset"],
                        "additional_parameters": group[0].get(
                            "additional_parameters",
                            group[0].get("additional_params"),
                        )
                        or {},
                        "weight": weights[-1],
                    }
                )

            combined, source_count = combine_daily_arrays(remapped, weights)
            combined.name = variable
            combined.attrs = attrs or {}
            combined.attrs.update(
                {
                    "polaris_combination_method": "weighted_mean",
                    "polaris_regridding_method": configuration["regridding_method"],
                }
            )
            output = target_template.copy()
            output[variable] = combined
            output["source_count"] = source_count
            output["cell_area"] = grid_cell_area(target_data)
            output.attrs.update(
                {
                    "title": configuration["display_name"],
                    "polaris_combination_method": "weighted_mean",
                    "polaris_minimum_daily_coverage": float(
                        configuration["minimum_daily_coverage"]
                    ),
                    "polaris_sources": json.dumps(provenance, sort_keys=True),
                }
            )
            output_path = unique_output_path(settings._standardized, unique_type="uuid")
            output.to_netcdf(output_path)
            timestamps = output["timestamp"]
            output_records.append(
                {
                    "repository": configuration["repository"],
                    "dataset": configuration["dataset"],
                    "variable": variable,
                    "spatial_resolution": target_records[0]["spatial_resolution"],
                    "temporal_resolution": configuration["temporal_resolution"],
                    "start_year": str(timestamps.dt.year.isel(timestamp=0).item()),
                    "start_month": f"{timestamps.dt.month.isel(timestamp=0).item():02d}",
                    "end_year": str(timestamps.dt.year.isel(timestamp=-1).item()),
                    "end_month": f"{timestamps.dt.month.isel(timestamp=-1).item():02d}",
                    "region": "COORDS",
                    "coordinates": target_records[0].get("coordinates"),
                    "additional_parameters": {},
                    "grid_type": "rectilinear",
                    "file_path": str(output_path),
                    "combined_sources": provenance,
                }
            )
    return output_records
