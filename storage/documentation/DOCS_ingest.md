# Ingesting data into Polaris system

## Steps to manually ingest data
1. Make sure the downloaded data jsonl file exists at the directory specified in `downloaded_data` in **config.yaml**. Each row of the file should contain one dictionary with metadata of a group of files that can be combined and standardized.

2. Standardize all files listed in the metadata of the **storage/data/downloaded/** directory. The standardized data will be stored in **storage/data/standardized/** and the downloaded files will be deleted once the standard ones are saved. In the terminal, run:

        python -m storage.ingest_data.standardize

3. Generate or validate every configured spatial container scheme:

        python -m storage.manage.space_containers

4. Create the complete spatio-temporal aggregate hierarchy. Every product is
   divided into blocks using its configured capacity:

        python -m storage.ingest_data.aggregate_data



## Standardizing data
Downloaded data is standardized as follows:
* Data interests that were split into various API requests (and thus downloaded into separate files) are consolidated into one file if possible
* The dimension names are standardized to `timestamp, longitude, latitude`
* The scientific variable names are standardized (so they will match across datasets)
* The latitude values are confirmed to be within range $[-90,90]$
* The longitude values are confirmed (or converted) to be within range $[0, 360)$
* The longitude and latitude values are sorted if the grid is rectilinear
* The grid type is added to the dataset metadata

Standardization code is in **polar-is/ingest_data/standardize.py**

## Splitting data by spatial containers
After standardization, every native grid cell is classified by its latitude
and longitude center. Cells assigned to the same container are
stored together as one block. Data values remain in their native grid and
projection.

This work is done by the script **polar-is/storage/ingest_data/make_data_blocks.py**.

### Containers
Currently, we define three containers that we give colloquial names: *buckets, basins, barrels*.
* Buckets - the canonical container whose size is defined in **config.yaml**. All other container capacities are defined as a factor of this container. In the code, buckets are named *Capacity-1*
* Basins - In the code, basins are *Capacity-2*. They are 2x larger than buckets.
* Barrels - In the code, barrels are *Capacity-4*. They are 4x larger than buckets.

Container information is stored in `container_schemes` in **config.yaml**.

## Index data
Each capacity has a JSONL metadata index describing its blocks. The information includes:
* Grid - original (and current) projection of data
* Datasets - names of datasets whose data can be found within the container
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

This is stored separately from the compact spatial container definitions.

Indexing function `index_data()` is in **ingest_data.py**.

* Curvilinear and projected grids are classified from their auxiliary
  longitude/latitude cell centers, so blocks align with the common containers
  while retaining the native grid.

## Store data
Store blocks by spatial container.

## Aggregate data and containers
We want to have a spatio-temporal hierarchy of pre-aggregated values so we can answer questions faster. Because we want to keep datasets in their native resolutions, we will aggregate, coarsen, the data spatially by a factor of 2 and a factor of 4 (keeping each dataset in its projection), and coarsen the data to any higher temporal resolution out of {Hour, Day, Month, Year}. 

Capacity 2 groups 2×2 capacity-1 containers and capacity 4 groups 4×4
capacity-1 containers. Their edge definitions are clipped when necessary.

Capacity-2 containers are grouped as follows:

```python
Starting with capacity-1 row 0 column 0 (r,c):
        Group (r,c) with (r+1, c), (r,c+1), (r+1, c+1)
        If r+1 or c+1 does not exist, group the containers that do exist
```

We coarsen native data to the desired resolution before splitting it into the
matching capacity. Every capacity/time combination uses the same block writer.

```
        Native resolution groups: ERA5  - (Capacity-1, H)       - Capacity-1=0.25, 0.5
                                  CARRA - (Capacity-1, 3H(?))   - Capacity-1=2.5km^2
                                  WHOI  - (Capacity-1, 3H)      - Capacity-1=0.25
                                  EMSST - (Capacity-1, D)       - Capacity-1=0.25

        (Resulting groups) - datasets with blocks in group
                          (Capacity-1, H) - ERA5  
                          (Capacity-1, 3H)- ERA5  CARRA(?)    WHOI
                          (Capacity-1, D) - ERA5  CARRA       WHOI    EMSST
                          (Capacity-1, M) - ERA5  CARRA       WHOI    EMSST
                          (Capacity-1, Y) - ERA5  CARRA       WHOI    EMSST

        Resulting groups: (Capacity-2, H) - ERA5   
                          (Capacity-2, 3H)- ERA5   CARRA(?)    WHOI
                          (Capacity-2, D) - ERA5   CARRA       WHOI    EMSST
                          (Capacity-2, M) - ERA5   CARRA       WHOI    EMSST
                          (Capacity-2, Y) - ERA5   CARRA       WHOI    EMSST

                          (Capacity-4, H) - ERA5   
                          (Capacity-4, 3H)- ERA5   CARRA(?)    WHOI
                          (Capacity-4, D) - ERA5   CARRA       WHOI    EMSST
                          (Capacity-4, M) - ERA5   CARRA       WHOI    EMSST
                          (Capacity-4, Y) - ERA5   CARRA       WHOI    EMSST

```
