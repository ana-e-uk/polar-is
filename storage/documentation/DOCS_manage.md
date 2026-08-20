# System Management Documentation

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
* `file_path`: string
