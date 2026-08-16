


def subset_rectilinear(ds, bounds, lat_name="latitude", lon_name="longitude"):
    return ds.sel(
        {
            lat_name: slice(bounds["lat_min"], bounds["lat_max"]),
            lon_name: slice(bounds["lon_min"], bounds["lon_max"]),
        }
    )

def subset_curvilinear(ds, bounds, lat_name="latitude", lon_name="longitude"):
    lat = ds[lat_name]
    lon = ds[lon_name]

    mask = (
        (lon >= bounds["lon_min"]) &
        (lon < bounds["lon_max"]) &
        (lat >= bounds["lat_min"]) &
        (lat < bounds["lat_max"])
    )

    return ds.where(mask, drop=True)

def subset_dataset_to_partition(ds, bounds, lat_name="latitude", lon_name="longitude"):
    grid_type = ds["grid_type"]

    if grid_type == "rectilinear":
        return subset_rectilinear(ds, bounds, lat_name, lon_name)

    if grid_type == "curvilinear":
        return subset_curvilinear(ds, bounds, lat_name, lon_name)

    raise ValueError(f"Unsupported grid type: {grid_type}")

def ingest_data():

    # Read in info on data to ingest from path in config.yaml's "new_file_info"
    # data_info = 
    # Read in partition metadata (defined in partitions.json)
    # partitions = 
    # file_sizes = {}
    # file_partitions = {}

    ########
    ######## PARTITION DATA NOTE: separate out into a function
    ########
    # For each partition p in partitions:

        # Open metadata file of p 
        # metadata_p = 
        # Get all dictionaries in data_info that intersect/overlap/fall within/touch the partition bounds
        #       data_info is a list of dicts where each dict corresponds to a file, 
        #       and each file has [min_lon, max_lon, min_lat, max_lat] in "coordinates" key

        # If there are dictionaries that correspond to the partition bounds of p:
            # Set p's boolean of having data to True
            # partitions[p["data"]] = 1

            # For each dict that corresponds to p:
                # Read in data
                # dat = 
                # Get subset that corresponds to p
                # subset = subset_dataset_to_partition(ds=dat, bounds=p[bounds])

                # Get information about this subset: 
                #       new_coordinates: [min_lon, max_lon, min_lat, max_lat]
                #       maxima: min value, max value
                #       size_of_subset_MB: size in MB of subset

                # Generate a new file name for subset
                # Get directory_path of p from metadata_p and create the file_path for this subset
                # Save subset to file_path

                # Save file size info and partition info for later
                # file_sizes[file_path]=size_of_subset_MB
                # if file_partitions[p["id"]]:
                    # file_partitions[p["id"]].append(file_path)
                # else:
                    # file_partitions[p["id"]]=[file_path]
                # Add subset information to metadata_p {"repository", "dataset", "variable", "start_year", "start_month", "end_year", "end_month",
                #                                       "temporal_resolution", "region", "new_coordinates", "grid_type", "spatial_resolution", "additional_params",
                #                                       "min_val", "max_val",  "file_path"}

            # Use stats.py functions to update stats regarding partitions: recalculate size of metadata_p, update largest/smallest partition file if needed
    
    # Use stats.py functions to update stats regarding files: 
    #       update largest/smallest file with file_sizes info if needed
    #       add len(file_sizes.keys) to storage original
    #       add sum of all file_sizes to totals storage
    #       update stats regarding metada: totals metadata should have 

    ########
    ######## AGGREGATE DATA NOTE: make into separate function or script / model after aggregate_data.py
    ########

    # Aggregation data will be stored in the same manner as the original data, but in a different directory.
    # i.e., the data will be stored in the folder corresponding to its partition, which we already know

    # Go through each partition
    # for p in file_partitions.keys:

        # cur_agg_dir = f"/data/aggregate/{p}/"

        # Aggregate each file in the list
        # for file_name in file_partitions[p]:
        
            # NOTE: store min/max/avg aggregation in the same file
            # time_agg_files = temporal_aggregation(file_name)    # generate day, month, year data for current file_name NOTE: how to not aggregate to finer grids (if data at monthly temporal resolution, just generate yearly data, not daily data)
            # space_agg_files = spatial_aggregation(time_agg_files)     # generate 2x,4x coarser data for current file_name and time_agg_files (list "time_agg_files" includes current file_name)

        # Save aggregate file info to p's metadata
        #      Open metadata file in cur_agg_dir
        #      Add time_agg_files and space_agg_files to metadata file

        # Save info in partitions.json if any new info for agg
        # Use stats.py functions to update stats that have changed (num files, etc.)

    pass