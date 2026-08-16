"""
Given data of interest, 
1. create a directory for each repository-dataset-variable request
    2. split request by time and space if needed, depending on repo
    3. generate API requests
    4. request and download data
    5. determine grid type, coordinate names for each file
    6. save information in csv: file_paths, repository, dataset, variable,
        spatial_resolution, temporal_resolution, start_year, start_month, end_year, 
        end_month, region, coordinates, additional_params
7. repeat for other requests


Group the interests given by userthat overlap in time and space, and 
split into reasonable sized requests, then call repository executors to
create the request, make API call to remote repo, and download data. 
Combine downloaded files together if the reasonable request size is too small
for individual files.

NOTE: interface handles having all correct inputs for each dataset, so this script
assumes that the input is correct.
"""

from dataclass import dataclass, replace, asdict
from typing import List, Any
import csv
from pathlib import Path
import yaml
import xarray as xr
import json

""" 
#####################################################################################
REMOTE REPOSITORY EXECUTORS
""" 
#
# Imports
#
from storage.initialize.get_remote_data.repo__copernicusclimatedatastore import executor as copernicusclimatedatastore_executor
from storage.initialize.get_remote_data.repo_nasaearthdata import executor as nasaearthdata_executor

#
# Dictionary
# 
EXECUTORS = {
        "Copernicus_ClimateDataStore": copernicusclimatedatastore_executor,
        "NASA_earthdata": nasaearthdata_executor,
    }
""" 
REMOTE REPOSITORY EXECUTORS
#####################################################################################
"""

Coordinates = tuple[float, float, float, float]      # [min_lon, max_lon, min_lat, max_lat]
AdditionalParameters = dict[str, Any]

@dataclass(frozen=True)
class DataRow:
    repository: str
    dataset: str
    variable: str
    start_year: str
    start_month: str
    end_year: str
    end_month: str
    temporal_resolution: str                            # H, D, M, Y
    region: str                                         # domain/other region defn. OR "COORDS"
    coordinates: Coordinates | None
    grid_type: str
    spatial_resolution: str                             # 0, 1, 2
    additional_params: AdditionalParameters | None
    row_idx: int

def merge_rows(rows: list[DataRow]) -> list[DataRow]:
    """
    Merge rows with the same repository, dataset, variable, region, and additional_params
    by taking the union of their time ranges and the union of their spatial resolutions iff
    they have overlapping or continuous time and space ranges/regions.
    """

    merged_list = []

    # while rows != empty:
        # Find rows with the same repository, dataset, variable, region, and additional_params
        
            # If time ranges overlap (end_time of one row >= start_time of another)

                # If spatial regions overlap ()

                    # Merge rows:
                    # merged = DataRow(...)   # use smallest time resolution and space resolution of all current rows
                    #                         # use min start_time, max end_time of all current rows
                    #                           if region="COORDS":
                    #                               make region="COORDS"
                    #                               make coordinates=[min min_lon, max max_lon, min min_lat, max max_lat] of all current rows
                    #                           else: 
                    #                               region=whatever matching value of current rows is
                    #                               coordinates=None
                    # merged_list.append(merged)    # add new row to list
                    # Delete current rows from rows
                
                # If spatial regions do NOT overlap

                    # Add current rows to merged_list
                    # Delete current rows from rows

            # If no time ranges of any rows overlap

                # Add current rows to merged_list
                # Delete current rows from rows

        # If no rows have the same base matching values: return merged_list + rows
    
    return merged_list

def from_month_index(index: int) -> tuple[str, str]:

    year, month_zero_based = divmod(index, 12)

    return str(year), f"{month_zero_based + 1:02d}"

def split_row_by_month(row: DataRow, row_idx: int) -> list[DataRow]:
    """
    For rows with time range (start_time, end_time) greater than one month, split row into
    multiple rows of monthly length. 
    """

    start = int(row.start_year) * 12 + (int(row.start_month) - 1)
    end = int(row.end_year) * 12 + (int(row.end_month) - 1)

    rows = []

    for index in range(start, end):
        start_year, start_month = from_month_index(index)
        end_year, end_month = from_month_index(index + 1)

        rows.append(
            replace(
                row,
                start_year=start_year,
                start_month=start_month,
                end_year=end_year,
                end_month=end_month,
                row_idx=row_idx,
            )
        )

    return rows

def split_rows_by_time(rows: List[DataRow]) -> list[DataRow]:

    i = 0   # Index to track original rows
    split_rows = []
    
    for r in rows:
        split_rows = split_rows + split_row_by_month(r, i)
        i += 1

    return split_rows

def write_rows(path: Path, rows: list[DataRow]) -> None:
    
    fieldnames = [
        "repository",
        "dataset",
        "variable",
        "start_year",
        "start_month",
        "end_year",
        "end_month",
        "temporal_resolution",
        "region",
        "coordinates",
        "spatial_resolution",
        "additional_params",
        "row_idx",
    ]

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow(asdict(row))

def generate_file_name() -> str:
    """Return randome file name"""
    # Get directory path from config.yaml file key "new_data_info"
    # Generate random number or use current time, or a combo of both
    return ""

def detect_grid_type(ds, lat_name="latitude", lon_name="longitude") -> str:
    lat = ds[lat_name]
    lon = ds[lon_name]

    if lat.ndim == 1 and lon.ndim == 1:
        return "rectilinear"

    if lat.ndim == 2 and lon.ndim == 2 and lat.dims == lon.dims:
        return "curvilinear"

    raise ValueError("Unsupported latitude/longitude coordinate structure")

def dim_names_to_standard(ds_dims, ds_coords) -> dict:
    
    lat_candidates = ["latitude", "lat", "y"]
    lon_candidates = ["longitude", "lon", "long", "x"]
    time_candidates = ["time", "timestamp", "datetime"]

    lat_dim = None
    lon_dim = None
    time_dim = None

    # Check dimensions first
    for dim in ds_dims:
        d = dim.lower()
        if d in lat_candidates:
            lat_dim = dim
        elif d in lon_candidates:
            lon_dim = dim
        elif d in time_candidates:
            time_dim = dim

    # Fallback: check coordinates if not found in dims
    if lat_dim is None:
        for coord in ds_coords:
            if coord.lower() in lat_candidates:
                lat_dim = coord

    if lon_dim is None:
        for coord in ds_coords:
            if coord.lower() in lon_candidates:
                lon_dim = coord

    if time_dim is None:
        for coord in ds_coords:
            if coord.lower() in time_candidates:
                time_dim = coord

    if lat_dim is None or lon_dim is None or time_dim is None:
        raise ValueError("Could not find latitude/longitude/time dimensions")

    dim_name_change_dict = {lat_dim: "latitude", lon_dim: "longitude", time_dim: "timestamp"}

    return dim_name_change_dict

def standardize_longitude_0_360(ds, lon_name="longitude"):
    lon = ds[lon_name]

    ds = ds.assign_coords({
        lon_name: lon % 360
    })

    if lon.ndim == 1:
        ds = ds.sortby(lon_name)

    return ds

def standardize_latitude_order(ds, lat_name="latitude"):
    lat = ds[lat_name]

    if lat.ndim == 1 and lat[0] > lat[-1]:
        ds = ds.sortby(lat_name)

    return ds

def combine_data(files_list: list) -> dict:
    """
    1. Standardize the coordinate names so each dataset that is stored has same name of coordinates
    2. Combine data from all files in the list by time if the resulting file size will not be too big. 
        (all data in files_list is from the same dataset and should be contiguous in time and space)
    3. Persist the new file, delete other files, and return the name of the new file and the file attributes:
        -   "repository", "dataset", "variable", "start_year", "start_month","end_year", "end_month",
            "temporal_resolution", "region", "coordinates", "spatial_resolution", "additional_params",
            "file_path"
    """
    # Read all data from paths in files_list using xarray
    data = 

    # Standardize dataset dimension names and dimensions longitude to 0-360, and latitude to ascending if grid is rectilinear
    # NOTE: How can I use/combine detect_grid_type function withiin dim_names_to_standard to make it work?
    standardized_data = data.rename(dim_names_to_standard(data.dims, data.coords))

    # Use xarray to combine data in the paths stored in files_list (put all data in one new file)
    combined_data = standardized_data.

    # Save combined data file
    file_path = generate_file_name()
    combined_data.to_netcdf(file_path)

    # Delete files that are now in combined file

    # Get the file attributes and save to final_file dict

    # final_file_dict = {
    #     "repository",
    #     "dataset",
    #     "variable",
    #     "start_year",
    #     "start_month",
    #     "end_year",
    #     "end_month",
    #     "temporal_resolution",
    #     "region",
    #     "coordinates",
    #     "grid_type",
    #     "spatial_resolution",
    #     "additional_params",
    #     "file_path",
    # }

    # return final_file_dict

def call_repo_executor(repository: str, dataset: str, query: dict) -> str:
    """
    Set the executor based on the repository input.
    """
    try:
        executor = EXECUTORS[repository]
    except KeyError:
        raise ValueError(f"Unknown repository: {repository}")
    
    temp_fn = generate_file_name()

    executor.run(dataset=dataset, query=query, temp_fn=temp_fn)

    return temp_fn

def remote_repository_requests(rows:list) -> list[str]:
    all_row_ids = []    # Get all the unique row indexes
    final_files_info = []   # Store file info of new data here

    # For each group of rows with the same row_idx (data split for easier download that, because it is the same dataset, can be joined again)
    for i in all_row_ids:

        temp_files_to_combine = []

        rows_in_group_i = rows[rows["row_idx"] == i]

        # For each row
        for row in rows_in_group_i:
            # Add file name of downloaded data to list
            temp_files_to_combine.append(call_repo_executor(
                repository="",
                dataset="",
                query=row,))
    
        # Combine download data into one file based on row idx
        final_files_info.append(combine_data(temp_files_to_combine))

    return final_files_info

def append_metadata(path: Path, record: dict[str, Any]) -> None:
    """Append one downloaded-data metadata record."""

    path.parent.mkdir(parents=True, exist_ok=True)

    # Convert Path objects to basic data types
    record = {
        **record,
        "file_paths": [str(file_path) for file_path in record["file_paths"]],
    }

    with path.open("a", encoding="utf-8") as file:
        json.dump(record, file)
        file.write("\n")

def execute():

    metadata_path = Path("storage/data/tmp/downloaded_data.jsonl")  #TODO: use config.py settings to get this path

    append_metadata(
        metadata_path,
        {
            "file_paths": [
                "",
            ],
            "repository": "",
            "dataset": "",
            "variable": "",
            "spatial_resolution": 0,
            "temporal_resolution": "1D",
            "start_year": "",
            "start_month":"",
            "end_year":"",
            "end_month":"",
            "region": "",
            "coordinates": {},
            "additional_params": {},
        },
    )

def OLD_execute():

    # Read in interests
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    rows = csv.DictReader(Path(config["interests_csv"]))

    rows = list(set(rows))      # Deduplicates list
    rows = merge_rows(rows)     # Group interests with overlapping time and space regions
    rows = split_rows_by_time(rows, config)     # Split requests into reasonable sizes w.r.t. APIs
    write_rows(Path(config["requests_csv"]), rows)   # Save rows
    new_data_info = remote_repository_requests(rows)    # Generate and execute requests

    # Write out file info containing new data matching interests
    with open(Path(config["new_data_info"]), "w") as f:
        json.dump(new_data_info, f, indent=2)   # NOTE: change to csv or??

    # Put indexing / processing of new data in "queue" (have it start when convenient)
    