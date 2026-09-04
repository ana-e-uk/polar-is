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
import xarray as xr
from pathlib import Path

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

    def __init__(self, relevant_data: list, query: dict):
        self.query_id: str      # string uniquely identifying query request so results of one function can be saved for additional function requests for same query
        self.relevant_data_list = relevant_data      # list with data dicts/rows of relevant files in storage
        self.temporal_resolution = query["temporal_resolution"]
        self.spatial_resolution = query["spatial_resolution"]
        self.aggregation = query["aggregation"]     # min, max, mean
        self.grid_type = query["grid_type"]     # projection answer should be in
        self.files_for_func_list: list

    class Timeseries(self):
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

    class Heatmap(self):
        def d_req(self):
            # Same as Timeseries d_req()
            # Specific func logic: needed data is the query spatial resolution and the coarsest temporal resolution of the daataset     
            pass

        def compute(self, data):
            # Same as Timeseries compute, but compute heatmap and calls to _generate_func_result_file_name() give func="heatmap"
            pass

    class FindTime(self):
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

    class FindArea(self):
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