"""

REMOTE REPOSITORY: Copernicus Climate Data Store

LINK: https://cds.climate.copernicus.eu/

DESCRIPTION: Generates and executes remote repository request for Copernicus Climate Data Store.
All requests to the Climate Data Store require the name of the dataset and the dataset-specific
parameters. To make an API request, an API key must be stored on the computer making the API call.

"""
from pathlib import Path
from storage.initialize.get_remote_data.get_remote_data import DataRow

"""
#####################################################################################
DATASET EXECUTORS
"""
#
# Imports
#
from storage.initialize.get_remote_data.repo__copernicusclimatedatastore.datasets import era5_single_level
from storage.initialize.get_remote_data.repo__copernicusclimatedatastore.datasets import carra_height

#
# Dictionary
#
DATASETS = {
    "ERA5_SINGLE": era5_single_level,
    "CARRA_HEIGHT": carra_height,
}
"""
#####################################################################################
DATASET EXECUTORS
"""

def confirm_api_key_exists():
    """
    API key must be stored in: $HOME/.cdsapirc

    Instructions:
    https://cds.climate.copernicus.eu/how-to-api
    """
    cdsapirc_file = Path.home() / ".cdsapirc"

    if not cdsapirc_file.is_file():
        raise FileNotFoundError(f"Copernicus Climate Data Store API key not found in: {cdsapirc_file}\n\nSee https://cds.climate.copernicus.eu/how-to-api.")

def month_index(year: str, month: str) -> int:
    return int(year) * 12 + (int(month) - 1)

def month_from_index(index: int) -> tuple[str, str]:
    year, month_zero_based = divmod(index, 12)
    return str(year), f"{month_zero_based + 1:02d}"

def requested_years(query: DataRow) -> list[str]:
    return [
        str(year)
        for year in range(int(query.start_year), int(query.end_year) + 1)
    ]

def requested_months(query: DataRow) -> list[str]:
    start = month_index(query.start_year, query.start_month)
    end = month_index(query.end_year, query.end_month)

    months = {
        month
        for index in range(start, end + 1)
        for _, month in [month_from_index(index)]
    }

    return sorted(months)

def request_area(query: DataRow) -> list[float] | None:
    if query.coordinates is None:
        return None

    min_lon, max_lon, min_lat, max_lat = query.coordinates

    return [max_lat, max_lon, min_lat, min_lon]  # N, E, S, W

def run(dataset: str, query: dict, temp_fn: str) -> list[str]:

    # Check repository can be called.
    confirm_api_key_exists()
    
    # Check dataset is supported.
    try:
        dataset_module = DATASETS[dataset]
    except KeyError:
        raise ValueError(f"\tUnknown dataset: {dataset}")
    
    # Build dataset-specific request dictionary.
    request = dataset_module.build_request(query)

    # Request and download data.
    client = cdsapi.Client()
    client.retrieve(dataset, request).download(temp_fn)

    return [temp_fn]