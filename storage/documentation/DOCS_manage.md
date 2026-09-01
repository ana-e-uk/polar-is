<!-- # System Management Documentation

## Dividing space into **buckets**
The bucket-grid origin and longitude/latitude bucket sizes are configured under `bucket_grid` in **polar-is/config.yaml**. The configured sizes must divide 360 degrees longitude and 180 degrees latitude exactly. The resulting groups are defined in **polar-is/storage/data/buckets.json**. The buckets are defined on a regular latitude-longitude grid, allowing datasets to be mapped to the same canonical space.

This json file has the name: "r{row index}_c{column index}" of each bucket. Each bucket contains:
* "id" - (stringing) the name of the bucket
* "row" - (integer) the row index (from 0 to 5)
* "col" - (integer) the column index (from 0 to 5)
* "bounds" - (dict) longitude and latitude maxima
* "data" - (list) place to store the file name(s) of data falling within this bucket.

The script that generates the json file is **polar-is/storage/manage/space_buckets.py**. The function `bucket_for_point()` returns the bucket corresponding to the given point (lon, lat).

## Determining bucket boundaries in dataset-native grids
Function `map_buckets()` in **polar-is/storage/manage/space_buckets.py** returns an array that assigns each data point a bucket. A data point (y, x) value is assumed to be the cell center and used to determine which bucket the data point corresponds to.

Currently, rectilinear and curvilinear inputs are supported. Projected datasets will require more metadata to be classified into the correct buckets.

Groups of data points from the same dataset that are sorted into the same bucket are stored together and refered to as a *data block* or *block*.

## Index: Bucket handles
A *bucket handle* contains information about the data stored in each bucket. Data is stored in *blocks*, and for each block, we keep:
* `repository`: string, 
* `dataset`: string, 
* `variable`: string, 
* `spatial_resolution`: float, 
* `temporal_resolution`: string, 
* `start_year`: string, 
* `start_month`: string, 
* `end_year`: string, 
* `end_month`: string, 
* `region`: string denoting official name of region (e.g. "east" or "west" for CARRA dataset), or "COORDS" to signify data has specific bounds, 
* `additional_params`: dictionary, 
* `grid_type`: string, 
* `dataset_bounds`: null | list with [min_lat, max_lat, min_lon, max_lon],
* `bucket_code`: integer, 
* `bucket_id`: string, 
* `block_summary`: dictionary that contains the minimum and maximum value of the cell center coordinates and the scientific variable,
* `file_path`: string -->

# System management

## Spatial containers

`container_grid` in `config.yaml` defines the authoritative capacity-1
regular longitude/latitude partition. `container_schemes` defines the storage,
metadata, definition path, and integer factor for every capacity.

`storage/manage/space_containers.py` derives all coarser definitions from
capacity 1. Coarse row and column counts use ceiling division, so the final
row or column is clipped at the global latitude/longitude maximum when a
factor does not divide the base grid dimensions.

Each definition contains:

- `id`, `code`, `container`, and `factor`
- `row` and `col`
- canonical longitude/latitude `bounds`
- `data`, the derived count of direct NetCDF block files

`map_containers()` classifies each native `(y, x)` cell by its longitude and
latitude center without reprojecting the data. Rectilinear and curvilinear
coordinates are supported.

## Block metadata

Every block record uses metadata schema version 2 and contains the source
dataset fields plus:

- `container`, `container_code`, and `container_id`
- `product_id` and `product_type`
- native and resulting temporal/spatial resolutions
- `spatial_coarsening_factor`
- temporal and spatial aggregation methods
- aggregation order/version and source paths
- `block_summary` with cell-center bounds and scientific-variable extrema
- `file_path`

Container codes and IDs are local to a capacity. The composite
`(container, container_code)` is the globally meaningful identity.

## Full list of block metadata columns
* repository - str - remote repository the data is from
* dataset - str - dataset the data is from
* variable - str 
* spatial_resolution - float
* temporal_resolution - str
* start_year - str - beginning of time interval of block
* start_month - str
* end_year - str - end of time interval of block
* end_month - str 
* region - str - official name of region (e.g. "east" or "west" for CARRA dataset), or "COORDS" to signify data has specific bounds
* additional_params - dict - any additional parameters that identify the dataset block
* grid_type - str - currently: rectilinear or curvilinear 
* dataset_bounds - list or null
* block_summary - dict {lat_min, lat_max, lon_min, lon_max, var_min, var_max}
* file_path - str - full direct file path
* container_code - int - directory info
* container_id - str
* container - str
* metadata_schema_version - int - versioning
* aggregation_version - int
* product_type - str - whether data is native or coarsened
* native_temporal_resolution - str
* native_spatial_resolution - int
* spatial_coarsening_factor - int - container capacity: 1, 2, 4
* temporal_aggregation_method - str or null
* spatial_aggregation_method - str or null
* aggregation_order - str - short description
* source_file_paths - list
* time_start - str
* time_end - str
* product_id - str - long identification number to avoid generating the same blocks
