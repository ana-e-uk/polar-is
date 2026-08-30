# Ingesting data into Polaris system

## Steps to manually ingest data
1. Make sure the downloaded data jsonl file exists at the directory specified in **config.yaml** in `downloaded_data`. Each row of the file should contain one dictionary with metadata of a group of files that can be combined and standardized.

2. Standardize all files listed in the metadata for the **storage/data/downloaded/** directory. The standardized data will be stored in **storage/data/standardized/** and the downloaded files will be deleted once the standard ones are saved. In the terminal, run:

        python -m storage.ingest_data.standardize

3. Make sure the buckets are defined and specified in **storage/data/buckets.jsonl**.

4. Divide the standardized data into blocks. Blocks will be stored in the directory corresponding to the bucket the block belongs to. In terminal, run: 

        python -m storage.ingest_data.make_data_blocks



## Standardizing data
Downloaded data is standardized as follows:
* Data interests that were split into various API requests (and thus downloaded into separate files) are consolidated into one file if possible
* The dimension names are standardized to `timestamp, longitude, latitude`
* The scientific variable names is standardized to the dataset that is 
* The latitude values are confirmed to be within range $[-90,90]$
* The longitude values are confirmed (or converted) to be within range $[0, 360)$
* The longitude and latitude values are sorted if the grid is rectilinear
* The grid type is added to the dataset metadata

Standardization code is in **polar-is/ingest_data/standardize.py**

## Spliting data by space buckets
After data has been downloaded and standardized, we can ingest it into Polaris. First, we divide data into *blocks*, one block for each of the space buckets the dataset overlaps. For data that is on the same regular latitude longitude grid as the buckets, we can split the data into their corresponding blocks by their center cell coordinates. For data that is on a different grid, we map the *common grid* buckets to the dataset grid, determine which bucket(s) each data cell center falls into (overlaps), and split the data into blocks with respect to these transformed boundaries.

This work is done by the script **polar-is/storage/ingest_data/make_data_blocks.py**.

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

## Aggregate data and buckets
<!-- Aggregate each block in a bucket. The buckets at coarser levels may be different than buckets at finer resolution levels. -->
We want to have a spatio-temporal hierarchy of pre-aggregated values so we can answer questions faster. Because we want to keep datasets in their native resolutions, we will aggregate, coarsen, the data spatially by a factor of 2 and a factor of 4 (keeping each dataset in its projection), and coarsen the data to any higher temporal resolution out of {Hour, Day, Month, Year}. 

The coarser spatial resolutions will be stored in coarser buckets.

Buckets are doubled in size each coarse factor. For example:

```python
Starting with bucket row 0 column 0 (r,c):
        Group (r,c) with (r+1, c), (r,c+1), (r+1, c+1)
        If r+1 or c+1 does not exist, just group the buckets that do exist
```

In order to create accurate coarser groups within the coarser buckets, we coarsen the native data to the desired resolution before splitting them into buckets. This also lets us treat the aggregated data as we do any other dataset and use the same code.

```
        Native resolution groups: ERA5  - (Fine, H)       - Fine=0.25, 0.5
                                  CARRA - (Fine, 3H(?))   - Fine=2.5km^2
                                  WHOI  - (Fine, 3H)      - Fine=0.25
                                  EMSST - (Fine, D)       - Fine=0.25

        (Resulting groups) - datasets with blocks in group
                          (Fine, H) - ERA5  
                          (Fine, 3H)- ERA5  CARRA(?)    WHOI
                          (Fine, D) - ERA5  CARRA       WHOI    EMSST
                          (Fine, M) - ERA5  CARRA       WHOI    EMSST
                          (Fine, Y) - ERA5  CARRA       WHOI    EMSST



        Resulting groups: (Coarse1, H) - ERA5   
                          (Coarse1, 3H)- ERA5   CARRA(?)    WHOI
                          (Coarse1, D) - ERA5   CARRA       WHOI    EMSST
                          (Coarse1, M) - ERA5   CARRA       WHOI    EMSST
                          (Coarse1, Y) - ERA5   CARRA       WHOI    EMSST

                          (Coarse2, H) - ERA5   
                          (Coarse2, 3H)- ERA5   CARRA(?)    WHOI
                          (Coarse2, D) - ERA5   CARRA       WHOI    EMSST
                          (Coarse2, M) - ERA5   CARRA       WHOI    EMSST
                          (Coarse2, Y) - ERA5   CARRA       WHOI    EMSST

```