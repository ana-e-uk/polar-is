# System Management Documentation

## Dividing space into **buckets**
The bucket-grid origin and longitude/latitude bucket sizes are configured under `bucket_grid` in **polar-is/config.yaml**. The configured sizes must divide 360 degrees longitude and 180 degrees latitude exactly. The resulting groups are defined in **polar-is/storage/data/buckets.json**. The buckets are defined on a regular latitude-longitude grid, allowing datasets to be mapped to the same canonical space.

This json file has the name: "r{row index}_c{column index}" of each bucket. Each bucket contains:
* "id" - (string) the name of the bucket
* "row" - (integer) the row index (from 0 to 5)
* "col" - (integer) the column index (from 0 to 5)
* "bounds" - (dict) longitude and latitude maxima
* "data" - (integer) derived count of NetCDF block files currently stored in this bucket's directory.

The script that generates the json file is **polar-is/storage/manage/space_buckets.py**. The function `bucket_for_point()` returns the bucket corresponding to the given point (lon, lat).

## Determining bucket boundaries in dataset-native grids
Function `map_buckets()` in **polar-is/storage/manage/space_buckets.py** returns an array that assigns each data point a bucket. A data point (y, x) value is assumed to be the cell center and used to determine which bucket the data point corresponds to.

Currently, rectilinear and curvilinear inputs are supported. Projected datasets will require more metadata to be classified into the correct buckets.

Groups of data points from the same dataset that are sorted into the same bucket are stored together and refered to as a *data block* or *block*.

## Index: Block handles
