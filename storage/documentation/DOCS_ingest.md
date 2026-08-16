# Ingesting data into Polaris system

## Standardizing data
Downloaded data is standardized as follows:
* Data interests that were split into various API requests (and thus downloaded into separate files) are consolidated into one file if possible
* The dimension names are standardized to `timestamp, longitude, latitude`
* The latitude values are confirmed to be within range $[-90,90]$
* The longitude values are confirmed (or converted) to be within range $[0, 360)$
* The longitude and latitude values are sorted if the grid is rectilinear
* The grid type is added to the dataset metadata

## Spliting data into the space buckets
After data has been downloaded and standardized, we can ingest it into Polaris. First, we divide data into *blocks*, one for each of the space buckets. For data that is on the same regular latitude longitude grid as the buckets, we can split the data into their corresponding blocks by their coordinates. For data that is on a different grid, we map the *common grid* buckets to the dataset grid, determine which bucket(s) the data falls into (overlaps), and split the data into blocks with respect to these transformed boundaries.

This work is done by the script **~/polar-is/storage/**

## Index data
We save the information (metadata) of each bucket in a file titled the same as the bucket. The information for each bucket is as follows:
* Grid - original (and current) projection of data
* Datasets - name of all the datasets whose data can be found within this bucket
* Dataset - each dataset keeps:
    * Dataset name
    * Repository name
    * Start year
    * Start month
    * End year
    * End month
    * Temporal resolution
    * Region
    * Coordinates
    * Spatial resolution
    * Variable
    * Additional parameters
    * Physical location range (currently file path)
* Bounds - total spatial ranges, temporal ranges, resolutions, variables. This can be used to filter out queries that definitely do not overlap with the current data.

This is stored in a separate file to keep the spatial bucket metadata small and allow the individual bucket information to grow if needed.

Indexing function `index_data()` is in **ingest_data.py**.

* We expose a queryable footprint in the common grid for curvilinear and projected grids by regridding the common grid bucket boundaries to the curvilinear/projected grids, then splitting the data in the native format by these regridded bucket boundaries. This creates data blocks that align with the common grid but retain the native data.

## Store data
Store data by bucket.

## Aggregate data
Aggregate each block in a bucket. The buckets at coarser levels may be different than buckets at finer resolution levels.