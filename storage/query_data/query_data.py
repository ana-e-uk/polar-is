"""
Given a query, find the requested data and return the result of requested computation.

The query will be passed in through an interface or through the command line (both refered to as API).
The query has the following information that overlaps with get_remote_data.py's DataRow class, but is not the same:
    
    function: list[str]     # list of functions to calculate (timeseries, heatmap, find time, find area)
    repository: Optional: str
    dataset: Optional: str
    variable: str
    start_year: int # format YYYY
    start_month: # must be in interval [1, 12]
    start_day: int # must be in interval [1, 31]
    start_time: str # format "HH:MM"
    end_year: int   # format YYYY
    end_month: int # must be in interval [1, 12]
    end_day: int # must be in interval [1, 31]
    end_time: str # format "HH:MM"
    temporal_resolution: str    # H, D, M, Y
    region: str     # domain/other region defn. OR "COORDS"
    coordinates: Coordinates | None     # Coordinates = tuple[float, float, float, float]      # [min_lon, max_lon, min_lat, max_lat]
    aggregation: str
    grid_type: str
    spatial_resolution: str     # 0, 1, 2
    additional_parameters:  AdditionalParameters | None     # AdditionalParameters = dict[str, Any]

This script checks the storage for relevant data by:
    0. If at any point, no data is found, 
        return message to API and ask if data should be downloaded. If yes, begin download process [Calls functions in storage.initialize.get_remote_data]
    1. Determine which "container capacity" should be used (depends on size of query region)
    2. Determining which "containers" the query overlaps --> this gets us the correct spatial resolution and region
    3. Opening the metadata of these containers
    4. Determining if any files within partition have the requested
        * time resolution --> this gets us the correct group subset
        * repo, dataset, and variable, time range, additional parameters
    5. If yes, refine spatial filter with coordinates --> this gets us the data to read for the query
    6. Determine which data to read and how
        * check if pre-aggregated data would help and if it exists
        * order of data to read to compute functions required
    7. Read data
    8. Compute calculation/query
    9. Return result
"""
import xarray as xr

# Input: query

# 1. Check which partitions the query overlaps: which partitions do the query bounds fall into/cover/pass through

# Initialize list to keep track of relevant files
# relevant_files = []

# 2. For each partition the query overlaps: # NOTE: maybe this can be done all at once instead of partition by partition, but I am not sure

#       Read in partition metadata file and make copy of metadata
#       metadata_p = 

#       3. If query specifies repository and dataset, 
#               filter metadata_p for files (info in dicts, but could be in rows depending on how it is stored) with this repo and dataset.
#          if not, 
#               no files are filtered out

#          Filter files by variable, then time range (file time range overlaps query time range)
#          Filter files by  additional parameters (will depend on dataset, assume no additional parameters for now)
#          CHECK if the union of the data time ranges completely cover query time range. If not, send message to user to ask to choose between cancel query or continue with current data and start download of the needed data.
#          FIND the minimum union of the data time ranges that completely cover the query time range. Filter out all other file dicts. The minimum union should have the least amount of files possible, so you'd probably start with the files with larger coverage so they are more likely to catch all the query range and you can find your "minimum" union set
#          Check each file and mark if temporal and spatial resolutions of file are finer, equal, or coarser than query resolutions in new file dict key value entry

#       4. If there are files that were not filtered out in step 3, check spatial coordinates of file overlap query (file in partition may not cover whole partition so we need to check candidate files actually have relevant data)
#          CHECK if the union of the spatial ranges of data completely cover the query spatial range. If not, send message to user to choose between cancle query or continue with current data and start download of the needed data.
#          FIND the minimum union of the data spatial ranges that completely cover query spatial range. Filter out all other file dicts
#          Add dicts that were not filtered out. These will be dicts of any file that does overlap query in the finer spatial check AND is part of the minimum union that covers the whole space.
#               * if a temporal/spatial resolution of a current relevant_file is finer than the query requested, edit the file_path to the correct aggregate sub-directory: /data/aggregate/{partition}/{temporal resolution}_{spatial resolution}/{file name} before adding it to the list
#          relevant_files.append(...)

# 5. Check relevant_files and plan how you will read the data

#    files_to_open = []
#    For each unique dataset d in relevant_files: 
#       d_list = relevant_files[relevant_files["dataset"]==d]
#       compute_obj = ComputeFunctions(d_list, query)
#       data_to_read = compute_obj.data_requirements()      # get list of files to read for this dataset

#    Determine which order to read data in files_to_open * initially just read by partition, so you make just one pass through all storage (not going back and forth from one partition to another etc.) maybe later it may be different/more complex
#    Read data in determined order (NOTE: actually more complicated because you want to read all the datasets at once but they're in different files. Would it work if you read subset of dataset A in partition r0_c2 into hold_1, then read subset of dataset B in partition r0_c2 into hold_2, then go to r0_c3 and add the subset of A to hold_1 and the subset of B to hold_2? I feel like this would be slower than just going through the data twice to grab first the files of A then the files of B).
#    6. compute_obj.execute(data)       # compute all the functions # PROBLEM: this object is defined within the for-loop, so only the last object remains, but need one for each dataset. This ties in to the problem of this section of wanting to read the data in an efficient way by splitting it into partitions but not being able to read it all at once/there's so much pre-computation to figure out what should be read anyway, which is most likely faster than just reading all the data, but I would like to run some tests to figure out if just storing everything in the same file is actually better when queries are small spatio-temporal regions and want multiple datasets together.

# 7. Return result

class ComputeFunctions():

    def __init__(self, relevant_data: list, query: dict):
        self.relevant_data = relevant_data      # list with data dicts/rows of relevant files in storage
        self.functions = query["functions"]     # list of functions to compute
        self.temporal_resolution = query["temporal_resolution"]
        self.spatial_resolution = query["spatial_resolution"]
        self.aggregation = query["aggregation"]     # min, max, mean
        self.grid_type = query["grid_type"]     # projection answer should be in

        self.data = list[xr.Dataset]       # will store the data read in by the main function...I feel like this is making things too complicated, but it might pay off in the end if the amount of data you have to read and aggregate goes from billions of values to like 20.

        self.timeseries_files = []
        self.heatmap_files = []
        self.find_time_files = []
        self.find_area_files = []

        self.timeseries_result = ""
        self.heatmap_result = ""

    class Timeseries():
        def d_req(self):
            # Determine what data resolution is needed to compute the timeseries
            # This will be the query temporal resolution and the coarsest spatial resolution of the dataset

            # For each file in self.relevant_data:
            #   if data resolutions are finer than needed, edit file path to get the more coarse data (the aggregation of data we do means that all coarser levels of a dataset will be available for all data, so if a finer resolution is there, the coarser version is there too)
            #   if data resolutions are coarser than needed, you know the finer data file DOES NOT EXIST because you are looking at the original data metadata, so you are looking at the files that are the finest already

            # Save required files to self.{function}_files
            # Return required files - should be same number of files (because we got the minimum set of files to cover all the query, so they (or their agg versions that cover the same space-time) are needed), maybe with different file paths
            pass

        def compute(self, data):
            # data will be from all files in self.{function}_files list, and should be the same resolution. If they are not the same resolution, we need to agg or weight the values first or treat the files separately so you don't give equal weight to a month average to an hour average for example
            # Compute the timeseries using data
            # Save result (x,y) as a csv
            # Plot data and save as png or jpeg idk
            pass

    class Heatmap():
        def d_req(self):
            # Determine what data resolution is needed to compute the heatmap
            # This will be the query spatial resolution and the coarsest temporal resolution of the daataset

            # For each file in self.relevant_data:
            #   if data resolutions are finer than needed, edit file path to get the more coarse data (the aggregation of data we do means that all coarser levels of a dataset will be available for all data, so if a finer resolution is there, the coarser version is there too)
            #   if data resolutions are coarser than needed, you know the finer data file DOES NOT EXIST because you are looking at the original data metadata, so you are looking at the files that are the finest already

            # Save required files to self.{function}_files
            # Return required files - should be same number of files (because we got the minimum set of files to cover all the query, so they (or their agg versions that cover the same space-time) are needed), maybe with different file paths
            
            pass

        def compute(self, data):
            # Compute heatmap using data
            # Save result (x,y,z) as csv
            # Plot data and save as png or jpeg
            pass

    class FindTime():
        def d_req(self):
            # Determine what data resolution is needed to compute find time
            # This will be the coarsest temporal and spatial resolutions of the datasets

            # For each file in self.relevant_data:
            #   if data resolutions are finer than needed, edit file path to get the more coarse data (the aggregation of data we do means that all coarser levels of a dataset will be available for all data, so if a finer resolution is there, the coarser version is there too)
            #   if data resolutions are coarser than needed, you know the finer data file DOES NOT EXIST because you are looking at the original data metadata, so you are looking at the files that are the finest already

            # Save required files to self.{function}_files
            # Return required files - should be same number of files (because we got the minimum set of files to cover all the query, so they (or their agg versions that cover the same space-time) are needed), maybe with different file paths
            
            pass
        def compute(self, data):
            # Check self.timeseries_result. If there is a csv file, use that, if not, use data
            # CSV file: you just check all the values and save results
            # Data: Filter data with query filter value (filter value and predicate (<, >, !=, ==, etc.) will be in additional_parameters)
            # Keep filtering data until there is no data that passes filter OR you reach the spatio-temporal resolution of the query
            # Save result (netcdf file with subset of data that passes filter)
            # Save result (time, bool) as csv
            # Plot data and save as png or jpeg
            pass

    class FindArea():
        def d_req(self):
            # Determine what data resolution is needed to compute find area
            # This will be the coarsest temporal and spatial resolutions of the datasets

            # For each file in self.relevant_data:
            #   if data resolutions are finer than needed, edit file path to get the more coarse data (the aggregation of data we do means that all coarser levels of a dataset will be available for all data, so if a finer resolution is there, the coarser version is there too)
            #   if data resolutions are coarser than needed, you know the finer data file DOES NOT EXIST because you are looking at the original data metadata, so you are looking at the files that are the finest already

            # Save required files to self.{function}_files
            # Return required files - should be same number of files (because we got the minimum set of files to cover all the query, so they (or their agg versions that cover the same space-time) are needed), maybe with different file paths
            
            pass

        def compute(self, data):
            # Check self.heatmap_result. If there is a csv file, use that, if not, use data
            # CSV file: you just check all the values and save results
            # Data: Filter data with query filter value (filter value and predicate (<, >, !=, ==, etc.) will be in additional_parameters)
            # Keep filtering data until there is no data that passes filter OR you reach the spatio-temporal resolution of the query
            # Save result (netcdf file with subset of data that passes filter)
            # Save result (lon,lat, bool) as csv
            # Plot data and save as png or jpeg
            pass

            
    def data_requirements(self):

        FUNCTIONS = {
            "timeseries": self.Timeseries,
            "heatmap": self.Heatmap,
            "find_time": self.FindTime,
            "find_area": self.FindArea,
        }

        # Get list of required files for each function
        required_files_list = []
        for f in self.functions:
            try:
                func = FUNCTIONS[f]
            except KeyError:
                raise ValueError(f"Unknown function: {f}")
            required_files_list.append(func.d_req())

        # Deduplicate list of required files
        required_files_list_unique = set(required_files_list)

        return required_files_list_unique

    def execute(self, data):
        self.data = data

        FUNCTIONS = {
                    "timeseries": [self.Timeseries, self.timeseries_files],
                    "heatmap": [self.Heatmap, self.heatmap_files],
                    "find_time": [self.FindTime, self.find_time_files],
                    "find_area": [self.FindArea, self.find_area_files],
                }
        
        # Run all functions
        for f in self.functions:
            func = FUNCTIONS[f][0]
            # Get subset of data needed
            data_for_f = FUNCTIONS[f][1]
            func.compute(data_for_f)