"""Plan and execute a query against the shared storage index."""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from polaris.config import Settings, get_settings
from storage.manage.space_containers import (
    container_definitions,
)


TIME_UNITS = ("Hour", "Day", "Month", "Year", "Source")
_TIME_PATTERN = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})"
    r"(?:-(?P<day>\d{2})(?:[T ](?P<hour>\d{2}))?)?$"
)
_TIME_UNIT_TO_RESOLUTION = {
    "Hour": "1H",
    "Day": "1D",
    "Month": "1MS",
    "Year": "1YS",
}
_PREDICATE_ALIASES = {
    "lt": "lt",
    "<": "lt",
    "le": "le",
    "<=": "le",
    "eq": "eq",
    "==": "eq",
    "ne": "ne",
    "!=": "ne",
    "ge": "ge",
    ">=": "ge",
    "gt": "gt",
    ">": "gt",
}


@dataclass(frozen=True)
class BoundingBox:
    """A storage query region using longitudes in the [0, 360) range."""

    west: float
    east: float
    south: float
    north: float


@dataclass(frozen=True)
class Query:
    """Normalized input shared by the API, CLI, and storage planner."""

    variable: str
    region: BoundingBox
    time_start: datetime
    time_end: datetime
    coarseness_factor: int
    time_unit: str
    function: str
    aggregation_method: str
    repository: str | None = None
    dataset: str | None = None
    additional_parameters: dict[str, Any] = field(default_factory=dict)
    predicate: str | None = None
    filter_value: float | None = None


@dataclass(frozen=True)
class RequestedDataGrid:
    """The spatial and temporal resolution requested by a query."""

    coarseness_factor: int
    time_unit: str


@dataclass(frozen=True)
class MatchingBlockGroup:
    """Time partitions from one dataset variant and product grid."""

    repository: str
    dataset: str
    variable: str
    additional_parameters: dict[str, Any]
    blocks: tuple[dict[str, Any], ...]
    dataset_variant_id: str = ""
    grid_id: str = ""
    grid_window: tuple[int, int, int, int] = (0, 0, 0, 0)


CoverageCell = tuple[str, datetime]


@dataclass(frozen=True)
class BlockGroupCoverage:
    """Spatio-temporal coverage for one matching block group."""

    group: MatchingBlockGroup
    hit_set: frozenset[CoverageCell]
    miss_set: frozenset[CoverageCell]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CoverageResult:
    """Coverage results for all block groups at the exact requested grid."""

    groups: tuple[BlockGroupCoverage, ...]
    unmatched_miss_set: frozenset[CoverageCell]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class QueryPlan:
    """Selected and grouped partitions plus their requested grid windows."""

    query: Query
    requested_data_grid: RequestedDataGrid
    index_records: tuple[dict[str, Any], ...]
    overlapping_bucket_ids: tuple[str, ...]
    matching_blocks: tuple[dict[str, Any], ...]
    block_groups: tuple[MatchingBlockGroup, ...]
    coverage: CoverageResult


def available_repositories(settings: Settings | None = None) -> tuple[str, ...]:
    settings = settings or get_settings()
    return tuple(settings.name_docs)


def available_datasets(
    repository: str | None = None,
    settings: Settings | None = None,
) -> tuple[str, ...]:
    settings = settings or get_settings()
    if repository is not None and repository not in settings.name_docs:
        return ()
    repositories = (
        {repository: settings.name_docs[repository]}
        if repository is not None
        else settings.name_docs
    )
    return tuple(
        sorted(
            {
                dataset
                for datasets in repositories.values()
                for dataset in datasets
            }
        )
    )


def available_variables(
    repository: str | None = None,
    dataset: str | None = None,
    settings: Settings | None = None,
) -> tuple[str, ...]:
    """Return canonical variables for the selected optional filters."""
    settings = settings or get_settings()
    variables = set()
    for repository_name, datasets in settings.name_docs.items():
        if repository is not None and repository_name != repository:
            continue
        for dataset_name, definition in datasets.items():
            if dataset is not None and dataset_name != dataset:
                continue
            variables.update(definition.get("variables", {}).values())
    return tuple(sorted(variables))


def available_additional_parameters(
    dataset: str,
    repository: str | None = None,
    settings: Settings | None = None,
) -> dict[str, tuple[Any, ...]]:
    """Return the union of dataset parameter options across repositories."""
    settings = settings or get_settings()
    parameters: dict[str, list[Any]] = {}
    for repository_name, datasets in settings.name_docs.items():
        if repository is not None and repository_name != repository:
            continue
        definition = datasets.get(dataset)
        if definition is None:
            continue
        for name, options in definition.get("additional_parameters", {}).items():
            values = parameters.setdefault(name, [])
            values.extend(option for option in options if option not in values)
    return {name: tuple(options) for name, options in parameters.items()}


def _normalize_region(value: Any) -> BoundingBox:
    if not isinstance(value, Mapping):
        raise ValueError("region must contain west, east, south, and north")
    names = ("west", "east", "south", "north")
    if any(name not in value for name in names):
        raise ValueError("region must contain west, east, south, and north")
    coordinates = {}
    for name in names:
        coordinate = value[name]
        if isinstance(coordinate, bool):
            raise ValueError(f"region {name} must be a number")
        try:
            coordinate = float(coordinate)
        except (TypeError, ValueError) as error:
            raise ValueError(f"region {name} must be a number") from error
        if not math.isfinite(coordinate):
            raise ValueError(f"region {name} must be finite")
        coordinates[name] = round(coordinate, 3)

    if not -180 <= coordinates["west"] < coordinates["east"] <= 180:
        raise ValueError("region must satisfy -180 <= west < east <= 180")
    if not -90 <= coordinates["south"] < coordinates["north"] <= 90:
        raise ValueError("region must satisfy -90 <= south < north <= 90")
    coordinates["west"] %= 360
    coordinates["east"] %= 360
    return BoundingBox(**coordinates)


def _normalize_time(value: Any, boundary: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"time_{boundary} must be a string")
    match = _TIME_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(
            f"time_{boundary} must be YYYY-MM, YYYY-MM-DD, or YYYY-MM-DDTHH"
        )
    parts = {
        name: int(part) if part is not None else None
        for name, part in match.groupdict().items()
    }
    year = parts["year"]
    month = parts["month"]
    day = parts["day"]
    hour = parts["hour"]
    try:
        if day is None:
            day = 1 if boundary == "start" else calendar.monthrange(year, month)[1]
        if hour is None:
            hour = 0 if boundary == "start" else 23
        return datetime(year, month, day, hour)
    except ValueError as error:
        raise ValueError(f"time_{boundary} is not a valid date-time") from error


def _optional_name(query: Mapping[str, Any], name: str) -> str | None:
    value = query.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def normalize_query(
    query: Mapping[str, Any],
    settings: Settings | None = None,
) -> Query:
    """Validate and normalize a query before storage planning."""
    settings = settings or get_settings()
    required = {
        "variable",
        "region",
        "time_start",
        "time_end",
        "coarseness_factor",
        "time_unit",
        "function",
        "aggregation_method",
    }
    missing = sorted(required - query.keys())
    if missing:
        raise ValueError(f"Missing required query fields: {', '.join(missing)}")

    repository = _optional_name(query, "repository")
    if repository is not None and repository not in available_repositories(settings):
        raise ValueError(f"Unsupported repository: {repository!r}")

    dataset = _optional_name(query, "dataset")
    if dataset is not None and dataset not in available_datasets(
        repository, settings
    ):
        raise ValueError(f"Unsupported dataset: {dataset!r}")

    variable = query["variable"]
    if not isinstance(variable, str) or variable not in available_variables(
        repository, dataset, settings
    ):
        raise ValueError(f"Unsupported variable: {variable!r}")

    raw_coarseness_factor = query["coarseness_factor"]
    if isinstance(raw_coarseness_factor, bool):
        raise ValueError("coarseness_factor must be an integer")
    try:
        coarseness_factor = int(raw_coarseness_factor)
    except (TypeError, ValueError) as error:
        raise ValueError("coarseness_factor must be an integer") from error
    if (
        isinstance(raw_coarseness_factor, float)
        and not raw_coarseness_factor.is_integer()
    ):
        raise ValueError("coarseness_factor must be an integer")
    if coarseness_factor not in settings.supported_coarseness_factors:
        raise ValueError(f"Unsupported coarseness factor: {coarseness_factor!r}")

    time_unit = query["time_unit"]
    if not isinstance(time_unit, str):
        raise ValueError(f"Unsupported time unit: {time_unit!r}")
    time_unit = time_unit.title()
    if time_unit not in TIME_UNITS:
        raise ValueError(f"Unsupported time unit: {time_unit!r}")

    function = str(query["function"]).lower().replace("_", "-")
    if function not in settings.supported_query_functions:
        raise ValueError(f"Unsupported function: {function!r}")

    aggregation_method = str(query["aggregation_method"]).lower()
    if aggregation_method not in settings.function_aggregation_methods:
        raise ValueError(
            f"Unsupported aggregation method: {aggregation_method!r}"
        )

    time_start = _normalize_time(query["time_start"], "start")
    time_end = _normalize_time(query["time_end"], "end")
    if time_start > time_end:
        raise ValueError("time_start must not be after time_end")

    additional_parameters = query.get("additional_parameters", {})
    if additional_parameters is None:
        additional_parameters = {}
    if not isinstance(additional_parameters, Mapping):
        raise ValueError("additional_parameters must be a dictionary")
    if additional_parameters and dataset is None:
        raise ValueError(
            "dataset is required when additional_parameters are specified"
        )
    allowed_parameters = (
        available_additional_parameters(dataset, repository, settings)
        if dataset is not None
        else {}
    )
    for name, value in additional_parameters.items():
        if name not in allowed_parameters:
            raise ValueError(f"Unsupported additional parameter: {name!r}")
        if value not in allowed_parameters[name]:
            raise ValueError(
                f"Unsupported value {value!r} for additional parameter {name!r}"
            )

    predicate = query.get("predicate")
    filter_value = query.get("filter_value")
    is_find_query = function in {"find-time", "find-area"}
    if is_find_query:
        predicate_key = predicate.lower() if isinstance(predicate, str) else None
        if predicate_key not in _PREDICATE_ALIASES:
            raise ValueError(
                "find-time and find-area require a supported predicate"
            )
        predicate = _PREDICATE_ALIASES[predicate_key]
        if isinstance(filter_value, bool):
            raise ValueError("filter_value must be a finite number")
        try:
            filter_value = float(filter_value)
        except (TypeError, ValueError) as error:
            raise ValueError("filter_value must be a finite number") from error
        if not math.isfinite(filter_value):
            raise ValueError("filter_value must be a finite number")
    elif predicate is not None or filter_value is not None:
        raise ValueError(
            "predicate and filter_value are only used by find-time and find-area"
        )

    return Query(
        variable=variable,
        region=_normalize_region(query["region"]),
        time_start=time_start,
        time_end=time_end,
        coarseness_factor=coarseness_factor,
        time_unit=time_unit,
        function=function,
        aggregation_method=aggregation_method,
        repository=repository,
        dataset=dataset,
        additional_parameters=dict(additional_parameters),
        predicate=predicate,
        filter_value=filter_value,
    )


def determine_requested_data_grid(query: Query) -> RequestedDataGrid:
    """Return the two resolution components that define the requested grid."""
    return RequestedDataGrid(query.coarseness_factor, query.time_unit)



def _longitude_intervals(region: BoundingBox) -> tuple[tuple[float, float], ...]:
    if region.west < region.east:
        return ((region.west, region.east),)
    if region.west > region.east:
        return ((region.west, 360.0), (0.0, region.east))
    return ((0.0, 360.0),)


def _record_overlaps_time(record: Mapping[str, Any], query: Query) -> bool:
    try:
        block_start = datetime.fromisoformat(record["time_start"])
        block_end = datetime.fromisoformat(record["time_end"])
    except (KeyError, TypeError, ValueError):
        return False
    return block_start <= query.time_end and block_end >= query.time_start


def _first_time_label(start: datetime, resolution: str) -> datetime:
    if resolution in {"1H", "3H", "1D"}:
        hours = {"1H": 1, "3H": 3, "1D": 24}[resolution]
        step = timedelta(hours=hours)
        origin = datetime(1970, 1, 1)
        step_count = math.ceil((start - origin) / step)
        return origin + step_count * step
    if resolution == "1MS":
        label = datetime(start.year, start.month, 1)
        return label if label >= start else _next_time_label(label, resolution)
    if resolution == "1YS":
        label = datetime(start.year, 1, 1)
        return label if label >= start else datetime(start.year + 1, 1, 1)
    raise ValueError(f"Unsupported coverage resolution: {resolution!r}")


def _next_time_label(timestamp: datetime, resolution: str) -> datetime:
    if resolution in {"1H", "3H", "1D"}:
        hours = {"1H": 1, "3H": 3, "1D": 24}[resolution]
        return timestamp + timedelta(hours=hours)
    if resolution == "1MS":
        if timestamp.month == 12:
            return datetime(timestamp.year + 1, 1, 1)
        return datetime(timestamp.year, timestamp.month + 1, 1)
    if resolution == "1YS":
        return datetime(timestamp.year + 1, 1, 1)
    raise ValueError(f"Unsupported coverage resolution: {resolution!r}")


def _expected_timestamps(
    query: Query,
    resolution: str,
) -> tuple[datetime, ...]:
    timestamp = _first_time_label(query.time_start, resolution)
    timestamps = []
    while timestamp <= query.time_end:
        timestamps.append(timestamp)
        timestamp = _next_time_label(timestamp, resolution)
    return tuple(timestamps)


def _coverage_group_name(group: MatchingBlockGroup) -> str:
    parameters = json.dumps(
        group.additional_parameters,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{group.repository}/{group.dataset}/{group.variable}/{parameters}"


@lru_cache(maxsize=64)
def _cached_jsonl(path: str, modified_ns: int, size: int) -> tuple[dict[str, Any], ...]:
    del modified_ns, size
    return tuple(
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _read_jsonl(path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    status = path.stat()
    return _cached_jsonl(str(path), status.st_mtime_ns, status.st_size)


def _overlapping_base_buckets(
    region: BoundingBox,
    settings: Settings,
) -> tuple[str, ...]:
    from storage.manage.space_containers import container_grid

    grid = container_grid("buckets", 1, **settings.container_grid)
    definitions = container_definitions(grid)
    longitude_intervals = _longitude_intervals(region)
    return tuple(
        bucket_id
        for bucket_id, definition in definitions.items()
        if definition["bounds"]["lat_min"] <= region.north
        and definition["bounds"]["lat_max"] > region.south
        and any(
            definition["bounds"]["lon_min"] <= east
            and definition["bounds"]["lon_max"] > west
            for west, east in longitude_intervals
        )
    )


def _intersect_window(
    partition: Mapping[str, Any],
    lookup: Mapping[str, Any],
) -> dict[str, int | str] | None:
    y_start = max(partition["grid_y_start"], lookup["grid_y_start"])
    y_stop = min(partition["grid_y_stop"], lookup["grid_y_stop"])
    x_start = max(partition["grid_x_start"], lookup["grid_x_start"])
    x_stop = min(partition["grid_x_stop"], lookup["grid_x_stop"])
    if y_stop <= y_start or x_stop <= x_start:
        return None
    return {
        "bucket_id": lookup["bucket_id"],
        "grid_y_start": y_start,
        "grid_y_stop": y_stop,
        "grid_x_start": x_start,
        "grid_x_stop": x_stop,
    }


def _group_partitions(
    records: tuple[dict[str, Any], ...],
) -> tuple[MatchingBlockGroup, ...]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (
            record["dataset_variant_id"],
            record["variable"],
            record["grid_id"],
            record["temporal_resolution"],
        )
        grouped.setdefault(key, []).append(record)
    results = []
    for key, partitions in grouped.items():
        windows = [
            window
            for partition in partitions
            for window in partition["query_windows"]
        ]
        results.append(
            MatchingBlockGroup(
                repository=partitions[0]["repository"],
                dataset=partitions[0]["dataset"],
                variable=key[1],
                additional_parameters=partitions[0]["additional_parameters"],
                blocks=tuple(partitions),
                dataset_variant_id=key[0],
                grid_id=key[2],
                grid_window=(
                    min(window["grid_y_start"] for window in windows),
                    max(window["grid_y_stop"] for window in windows),
                    min(window["grid_x_start"] for window in windows),
                    max(window["grid_x_stop"] for window in windows),
                ),
            )
        )
    return tuple(results)


def _partition_coverage(
    query: Query,
    requested_data_grid: RequestedDataGrid,
    overlapping_bucket_ids: tuple[str, ...],
    groups: tuple[MatchingBlockGroup, ...],
) -> CoverageResult:
    if not groups:
        warning = "No matching product partitions exist at the exact requested grid."
        return CoverageResult((), frozenset(), (warning,))
    results = []
    warnings = []
    for group in groups:
        if requested_data_grid.time_unit == "Source":
            resolutions = {
                partition.get("source_temporal_resolution")
                for partition in group.blocks
            }
            resolution = resolutions.pop() if len(resolutions) == 1 else None
        else:
            resolution = _TIME_UNIT_TO_RESOLUTION[requested_data_grid.time_unit]
        if resolution is None:
            warning = (
                f"Cannot check source coverage for {_coverage_group_name(group)}."
            )
            results.append(
                BlockGroupCoverage(group, frozenset(), frozenset(), (warning,))
            )
            warnings.append(warning)
            continue
        timestamps = _expected_timestamps(query, resolution)
        expected = frozenset(
            (bucket_id, timestamp)
            for bucket_id in overlapping_bucket_ids
            for timestamp in timestamps
        )
        hits = set()
        for partition in group.blocks:
            start = datetime.fromisoformat(partition["time_start"])
            end = datetime.fromisoformat(partition["time_end"])
            buckets = {
                window["bucket_id"] for window in partition["query_windows"]
            }
            hits.update(
                (bucket_id, timestamp)
                for bucket_id in buckets
                for timestamp in timestamps
                if start <= timestamp <= end
            )
        hit_set = frozenset(hits) & expected
        miss_set = expected - hit_set
        group_warnings = ()
        if miss_set:
            warning = (
                f"{_coverage_group_name(group)} is missing {len(miss_set)} "
                f"of {len(expected)} bucket/time cells."
            )
            group_warnings = (warning,)
            warnings.append(warning)
        results.append(
            BlockGroupCoverage(group, hit_set, miss_set, group_warnings)
        )
    return CoverageResult(tuple(results), frozenset(), tuple(warnings))


def plan_query(
    query: Query | Mapping[str, Any],
    settings: Settings | None = None,
) -> QueryPlan:
    """Plan against the shared product index and per-grid bucket lookups."""
    settings = settings or get_settings()
    normalized = query if isinstance(query, Query) else normalize_query(query, settings)
    requested = determine_requested_data_grid(normalized)
    index_records = _read_jsonl(settings.product_index)
    datasets = {
        record["dataset_variant_id"]: record
        for record in _read_jsonl(settings.datasets_catalog)
    }
    overlapping_buckets = _overlapping_base_buckets(normalized.region, settings)
    lookup_cache: dict[str, tuple[dict[str, Any], ...]] = {}
    matches = []
    for raw_record in index_records:
        dataset = datasets.get(raw_record.get("dataset_variant_id"))
        if dataset is None:
            continue
        parameters = dataset.get("additional_parameters") or {}
        if raw_record.get("variable") != normalized.variable:
            continue
        if raw_record.get("coarseness_factor") != requested.coarseness_factor:
            continue
        if raw_record.get("temporal_resolution") != requested.time_unit:
            continue
        if not _record_overlaps_time(raw_record, normalized):
            continue
        if (
            normalized.repository is not None
            and dataset["repository"] != normalized.repository
        ):
            continue
        if normalized.dataset is not None and dataset["dataset"] != normalized.dataset:
            continue
        if any(
            parameters.get(name) != value
            for name, value in normalized.additional_parameters.items()
        ):
            continue
        grid_id = raw_record["grid_id"]
        if grid_id not in lookup_cache:
            lookup_cache[grid_id] = _read_jsonl(
                settings.bucket_lookup_dir / f"{grid_id}.jsonl"
            )
        windows = []
        for lookup in lookup_cache[grid_id]:
            if lookup["bucket_id"] not in overlapping_buckets:
                continue
            intersection = _intersect_window(raw_record, lookup)
            if intersection is not None:
                windows.append(intersection)
        if not windows:
            continue
        source_resolution = (
            dataset.get("variables", {})
            .get(normalized.variable, {})
            .get("source_temporal_resolution")
        )
        matches.append(
            {
                **raw_record,
                "repository": dataset["repository"],
                "dataset": dataset["dataset"],
                "additional_parameters": parameters,
                "source_temporal_resolution": source_resolution,
                "query_windows": windows,
            }
        )
    matching = tuple(matches)
    groups = _group_partitions(matching)
    coverage = _partition_coverage(
        normalized,
        requested,
        overlapping_buckets,
        groups,
    )
    return QueryPlan(
        query=normalized,
        requested_data_grid=requested,
        index_records=index_records,
        overlapping_bucket_ids=overlapping_buckets,
        matching_blocks=matching,
        block_groups=groups,
        coverage=coverage,
    )
