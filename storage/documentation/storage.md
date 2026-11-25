# POLAR-IS storage details

## storage

**`bucket_lookup.py`** maps buckets to grids.

**`catalog.py`** describes the grid catalog.

**`grid_topology.py`** helpers for working with grids.

**`space_containers.py`** defines buckets.


## data/

**`downloaded_data.jsonl`** includes:
```text
file_paths
repository
dataset
variable
spatial_resolution
temporal_resolution
time information
region/coordinates
additional parameters
```

**`datasets.jsonl`** stores dataset metadata.

**`grids.jsonl`** keeps `grid_id` for each grid. A per-grid [bucket lookup](../data/data/bucket_lookup/) maps the shared geographic buckets to rectangular windows on that grid.

**`metadata.jsonl`** is the shared product index that stores information of all products: relative paths, time ranges, coarseness, and other metadata.

**`query_log.jsonl`** stores information about each accepted job from both the web interface and the command-line interface.

**Structure of physical storage**
```text
storage/data/
├── catalogs/
|   ├── datasets.jsonl
|   ├── grids.jsonl
|   └── grids/<grid_id>.nc
|
├── bucket_lookup/<grid_id>.jsonl
├── products/
|   └── <dataset_variant>/<variable>/<time-unit>/coarsen_<factor>/*.nc
|
├── tmp/
|   ├── downloaded/
|       └── downloaded_data.jsonl
|   ├── query_results/
|   └── standardized/
|
├── metadata.jsonl
└── query_log.jsonl

```

## ingest_data/
Ingesting data has four main parts:

1. Download/add *source* data to storage.
    * **Method 1:** A user may manually add data to the storage and populate its information to `downloaded_data.jsonl`.
    * **Method 2:** A user may provide a list of data of interest specifying the repository, dataset, variable, time range, spatial range (including height or similar parameter if needed), and the expected finest resolution needed for that variable. POLAR-IS will use this to download data and populate `download_data.jsonl`.
    ```bash
    python -m 
    ```
2. Standardize *source* files.
    * **Dimensions are renamed** to the internal convention `timestamp, y, x` and coordinates to `latitude, longitude, projection_y, projection_x`.
    * Converts longitude to [0,360), sorts rectilinear latitude/longitude axes and validates latitude bounds.
    * **Source variable names are mapped** to canonical POLAR-IS variable names from `config.yaml`.
    * **Reusable grid topology** is added:
        * Rectilinear grids receive inferred lat/lon bounds.
        * Curvilinear metadata is converted to a CF grid mapping and projected X/Y coordinates
        * Singleton technical source coordinates are moved into dataset metadata.
        * `standardized_metadata.jsonl` is a temporary file that records standardized files.
    ```bash
    python -m storage.ingest_data.standardize
    ```
3. Build data *prducts*
    * **Product policy** is defined in `product_policy` function in `aggregate_data.py` and spatial/temporal aggregate methods in `config.yaml`.
        * Currently: Source is kept at a spatial coarseness factor of 1, temporal products are strictly coarser than the source resolution. Factor 2 coarseness is computed for Month and Year. 
    * **Spatial coarsening** is done in native projections.
    * **Temporal aggregation** only builds temporal products coarser than the source temporal resolution.
    * **Sufficient statistics** are used to calculate cell-area-weighted means.
    * **Products are split** by time only: Source, Hour, and Day into monthly files; Month and Year into yearly files. 
    ```bash
    python -m storage.ingest_data.aggregate_data
    ```
4. OPTIONAL: Build a Combined dataset
    * **Combine standardized datasets** steps:
        a. aggregate to the temporal resolution if >= 75% of expected source observations are present.
        b. regird data from (a) to the target grid using xESMP bilinear interpolation and *keep weight files to reuse*.
        c. compute weighted mean using available sources at each cell.
        * Currently: data is combined into a spatio-temporal resolution of 0.5 degrees, Daily (using ERA5's rectilinear grid). 
    * **Store number of contributing datasets** for each time/cell as `source_count`.
    ```bash
    python -m 
    ```

## query_data/

**`query_data.py`** defines the query validator and query planner.
* Required input:
    * Canonical variable name
    * Geographic bounding box
    * Start and end time
    * Exact time unit: Source, Hour, Day, Month, or Year
    * Exact spatial coarseness factor: 1, 2
    * Query function
    * Aggregation method
    * Predicate and value for filtering queries
* Optional input:
    * Repository and dataset filters
    * Additional dataset parameters
* Query planner steps:
    1. Find coarse geographic buckets intersecting the requested bounding box.
    2. Filters index records by variable, filters, product, time overlap, and grid.
    3. Intersects bucket windows with partition grid windows.
    4. Groups matching partitions by dataset variant, variable, grid, and product.
    5. Estimates bucket/time coverage and emits warnings for gaps.

**`executor.py`** executes the job (query).
1. Loads the canonical grid once per process/file version.
2. Reconstructs the selected product grid at the requested coarseness.
3. Uses bucket windows as a coarse spatial filter.
4. Calculates an exact latitude/longitude cell mask before opening product data.
5. Opens only matching time partitions.
6. Slices by timestamp and y/x window.
7. Loads only the required statistics.
8. Masks cells outside the exact geographic region.
9. Concatenates multiple time partitions and removes duplicate timestamps.
10. Produces one output group per matching dataset variant/grid.
