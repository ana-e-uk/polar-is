# System Management Documentation

## Dividing space into **buckets**
Currently, we split the world into latitude longitude rectangular regions of size 60 longitude and 30 latitude. This results in 36 groups, or buckets that are defined in **~/polar-is/storage/data/buckets.json**. The buckets are defined on a regular latitude longitude grid projection. This world-wide projection allows us to map any regional projection to the same space.

This json file has the name: "r{row index}_c{column index}" of each bucket. Each bucket contains:
* "id" - (string) the name of the bucket
* "row" - (integer) the row index (from 0 to 5)
* "col" - (integer) the column index (from 0 to 5)
* "bounds" - (dict) longitude and latitude maxima
* "data" - (list) place to store the file name(s) of data falling within this bucket.

The script that generates the json file is **~/polar-is/storage/manage/space_buckets.py**. The function `bucket_for_point()` returns the bucket corresponding to the given point (lon, lat).

## Determining bucket boundaries in dataset-native grids
Function `map_buckets()` in **~/polar-is/storage/manage/space_buckets.py** returns an array that assigns each data point a bucket. A data point (y, x) value is assumed to be the cell center and used to determine which bucket the data point corresponds to.

Currently, rectilinear and curvilinear inputs are supported. Projected datasets will require more metadata to be classified into the correct buckets.