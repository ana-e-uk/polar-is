"""
Given a query, find the requested data and return the result of requested computation.

This script checks the storage for relevant data by:
    0. If at any point, no data is found, 
        return message to API and ask if data should be downloaded. If yes, begin download process [Calls functions in storage.initialize.get_remote_data]
    1. Determine which "container capacity" should be used (depends on size of query region)
    2. Determining which "containers" the query overlaps with storage.ingest_data.make_data_blocks.block_bounds_and_extrema
        --> this gets us the correct spatial resolution and region
    3. Open metadata of containers and determine if any files within partition have the requested
        * time resolution --> this gets us the correct group subset
        * repo, dataset, and variable, time range, additional parameters
    4. If yes, refine spatial filter with coordinates with storage.query_data.space_containers.map_containers OR container_for_point
        --> this gets us the data to read for the query
    5. Determine which data to read and how
        * check if pre-aggregated data would help and if it exists
        * order of data to read to compute functions required
    6. Read data
    7. Compute calculation/query
    8. Return result
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime
import math
from pathlib import Path
import re
from typing import Any, Mapping

from polaris.config import Settings, get_settings


TIME_UNITS = ("Hour", "Day", "Month", "Year", "Source")
_TIME_PATTERN = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})"
    r"(?:-(?P<day>\d{2})(?:[T ](?P<hour>\d{2}))?)?$"
)


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
    if coarseness_factor not in settings.coarseness_to_spatial_level:
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
    )

def _found_missing_data(missing: dict) -> bool:
    '''Generates API message about missing data. 
    Asks user if it should be downloaded and returns answer.'''

def _get_query_region_size():
    '''Compute and return area of query region.'''

def _match_query_to_container_size(area: float):
    '''Return the container directory that should be used. 
    Choose the largest container with:
        * size smaller than the area of the query.
        * size only marginally larger than the area of the query.
    '''
    allowed_buffer: float # difference in area that container size can be
    container_areas = {}    # area of all containers (currently: capacity 1, 2, 4)

def _get_overlap_of_query_region_and_containers():
    '''Return all containers that the query region overlaps.'''
    #  maybe: use storage.ingest_data.make_data_blocks.block_bounds_and_extrema

def _read_container_metadata(capacity: str):
    '''Read the metadata.jsonl for the containers of the given capacity.'''

def _filter_containers():
    '''Filter container by their metadata by other query parameters:
        time resolution, repo, dataset, and variable, time range, additional parameters
    '''

def _refine_spatial_overlap():
    '''Filter out containers that do not overlap query region at any point.'''

def _check_coverage_time_range():
    '''Check if the local data covers the time range of the query.
    If not, return missing range(s) to call found_missing_data()
    '''

def _check_coverage_space_range():
    '''Check if the local data covers the spatial region of the query.
    If not, return missing range(s) to call found_missing_data()
    '''

def _find_coarser_data(space_res: float, temp_res: str):
    '''Check if any coarser version of the data exists.'''

def _generate_func_result_file_name(query_id: str, func: str, file_type: str) -> Path:
    '''Return file name to store resulting csv/png/jpeg/json for a specific query. '''

def _get_data():
    '''Read in data. NOTE: Can probably use function in storage.ingest_data or other'''

class QueryStorage():

    def __init__(
        self,
        relevant_data: list,
        query: Query | Mapping[str, Any],
    ):
        self.query = query if isinstance(query, Query) else normalize_query(query)
        self.query_id: str      # string uniquely identifying query request so results of one function can be saved for additional function requests for same query
        self.relevant_data_list = relevant_data      # list with data dicts/rows of relevant files in storage
        self.files_for_func_list: list = []

    class Timeseries:
        def d_req(self):
            # Determine what data resolution is needed to compute the timeseries
            # Specific func logic: needed data is the query temporal resolution and the coarsest spatial resolution of the dataset

            # For each file in self.relevant_data:
            #   if data resolutions are finer than needed, edit file path to get the more coarse data (the aggregation of data we do means that all coarser levels of a dataset will be available for all data, so if a finer resolution is there, the coarser version is there too)
            #   if data resolutions are coarser than needed, you know the finer data file DOES NOT EXIST because you are looking at the original data metadata, so you are looking at the files that are the finest already

            # Save file names in self.files_for_func_list
            pass

        def compute(self, data):
            # Read in data in self.files_for_func_list. They should be the same resolution. If they are not the same resolution, we need to agg or weight the values first or treat the files separately so you don't give equal weight to a month average to an hour average for example
            # Compute the timeseries using data
            # Save result (x,y) as a csv (or json or jsonl, etc. whichever is easier) in storage.data.tmp.query_results under file from _generate_func_result_file_name(self.query_id, "timeseries", "csv")
            # Plot data and save as png (or jpeg, etc. whichever is easier) under file from _generate_func_result_file_name(query_id=self.query_id, func="timeseries", file_type="png/jpg")
            pass

    class Heatmap:
        def d_req(self):
            # Same as Timeseries d_req()
            # Specific func logic: needed data is the query spatial resolution and the coarsest temporal resolution of the daataset     
            pass

        def compute(self, data):
            # Same as Timeseries compute, but compute heatmap and calls to _generate_func_result_file_name() give func="heatmap"
            pass

    class FindTime:
        '''Return all time points p where p {predicate} {filter_value}
        
        e.g. for filter_value = 267, predicate = <, return all time points p that satisfy: p < 267 with bool=1,
        return bool=0 for all other points in time range that do not

        filter value and predicate (<, >, !=, ==, etc.) are in query["additional_parameters"]
        '''

        def d_req(self):
            # Same as Timeseries d_req()
            # Specific func logic: needed data is the coarsest temporal and spatial resolutions of the datasets
            pass

        def compute(self, data):
            # Check if timeseries csv file exists, if yes, use that, if not, read in and use data
                # CSV file: filter timeseries values with query filter value and predicate, and save results
                    # **Make sure the timeseries results can be used to accurately answer find time query** 
                    # e.g. predicate == cannot be answered using average timeseries results
                    # Note CSV file may be able to be an initial filter to look at less data
                # Data: filter out time intervals using coarser resolution data until you reach requested query spatio-temporal resolution. I.e., Keep filtering data until there is no data that passes filter OR you reach the spatio-temporal resolution of the query and you return the leftovers as the result
                    # E.g. say query is find p < 267 at spatio-temporal resolution coarse-2-Day, you have no timeseries results, and the coarsest data is coarse-4-Year
                        # Use coarse-2 data (requested resolution) for all these checks: 
                            # If any year in time range has a min greater than 267, we know there are no values < 267 in that whole year, so we can filter out that year
                            # For all years not filtered out, check all their monthly values in the same way
                            # If any months in time range are not filtered out, check days within these months the same way.
                            # Do not check Hours because requested resolution is Day
            # Save result (netcdf file with subset of data that passes filter) 
            # Save result (time, bool) as csv
            # Plot data and save as png or jpeg
            pass

    class FindArea:
        '''Return all spatial regions p where p {predicate} {filter_value}
                
            e.g. for filter_value = 267, predicate = <, return all spatial points p that satisfy: p < 267 with bool=1,
            return bool=0 for all other points in time range that do not
    
            filter value and predicate (<, >, !=, ==, etc.) are in query["additional_parameters"]
        '''
        
        def d_req(self):
            # Same as FindTime d_req()
            pass

        def compute(self, data):
            # Very similar to FindTime
            # Check if heatmap csv file exists, if yes, use that, if not, read in and use data
            # CSV file: analogous to FindTime compute()
            # Data: filter out spatial regions/containers/partitions/blocks until you reach requested query spatio-temporal resolution. I.e., Keep filtering data until ther eis no data that passes filter OR you reach the spatio-temporal resulution of the query and return the leftovers as the result
                # E.g. say query is find p < 267 at spatio-temporal resolution coarse-2-Day, you have no heatmap results, and the coarsest data is coarse-4-Year
                    # Use Day data (requested resolution) for all these checks:
                        # If any coarse-4 container/partition/block in spatial range has min greater than 267, we know there are no values < 267 in the whole region, so we can filter out that container/partition/block
                        # If any coarse-4 regions are not filtered out, check its corresponding coarse-2 regions the same way
                        # Do not check coarse-1 because the requested resolution is coarse-2
            # Save result (netcdf file with subset of data that passes filter)
            # Save result (lon,lat, bool) as csv
            # Plot data and save as png or jpeg
            pass

    def query_data(self, func: str):
        pass
