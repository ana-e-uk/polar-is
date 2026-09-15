# Ingesting data into Polaris system

## Steps to manually ingest data
1. Make sure the downloaded data jsonl file exists at the directory specified in `downloaded_data` in **config.yaml**. Each row of the file should contain one dictionary with metadata of a group of files that can be combined and standardized.

2. Standardize all files listed in the metadata of the **storage/data/downloaded/** directory. The standardized data will be stored in **storage/data/standardized/** and the downloaded files will be deleted once the standard ones are saved. In the terminal, run:

        python -m storage.ingest_data.standardize

3. Generate or validate every configured spatial container scheme:

        python -m storage.manage.space_containers

4. Create the complete spatio-temporal aggregate hierarchy. Every product is
   divided into blocks using its configured capacity. When enabled, the
   Combined dataset is built first from standardized daily source values and
   then passed through this same hierarchy:

        python -m storage.ingest_data.aggregate_data

   Combined requires an environment containing xESMF and ESMF/ESMPy. Its
   target grid, daily coverage threshold, eligible variables, source weights,
   remapping method, and reusable weight-cache directory are configured under
   `combined_dataset` in **config.yaml**.



## Standardizing data
Downloaded data is standardized as follows:
* Data interests that were split into various API requests (and thus downloaded into separate files) are consolidated into one file if possible
* The dimension names are standardized to `timestamp, longitude, latitude`
* The scientific variable names are standardized (so they will match across datasets)
* The latitude values are confirmed to be within range $[-90,90]$
* The longitude values are confirmed (or converted) to be within range $[0, 360)$
* The longitude and latitude values are sorted if the grid is rectilinear
* The grid type is added to the dataset metadata
* Stable zero-based `source_y_index` and `source_x_index` coordinates are
  assigned before any spatial block is created
* Native source spans and requested-grid indices are retained so coarsened
  cells remain identifiable without assuming the query result is rectangular
* Rectilinear coordinate bounds are retained for cell geometry
* CARRA's GRIB Lambert definition is translated to CF grid-mapping metadata,
  metre-based `projection_x`/`projection_y` coordinates, and CRS WKT

Standardization code is in **polar-is/ingest_data/standardize.py**

## Splitting data by spatial containers
After standardization, every native grid cell is classified by its latitude
and longitude center. Cells assigned to the same container are
stored together as one block. Data values remain in their native grid and
projection.

Query execution flattens selected data to `(timestamp, cell)`. Each cell keeps
its source index, source span, output-grid index, geographic center, bucket
provenance, and four geographic corners. Projected grids additionally retain
their projected center and CF grid mapping. Stable `cell_id` values include the
source group, coarseness factor, and output-grid indices.

This work is done by the script **polar-is/storage/ingest_data/make_data_blocks.py**.

### Spatial levels and buckets
The common map is divided into buckets at three spatial levels:
* Capacity-1 is the canonical bucket size.
* Capacity-2 buckets are twice as large.
* Capacity-4 buckets are four times as large.

Container information is stored in `container_schemes` in **config.yaml**.

## Index data
Each spatial level has a JSONL metadata index describing its blocks. The information includes:
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
* Bounds - total spatial ranges, temporal ranges, resolutions, variables. This can be used to filter out queries that definitely do not overlap with the current data.

Block paths are derived from spatial level, bucket ID, and block ID rather
than stored in the index.

This is stored separately from the compact spatial container definitions.

Indexing function `index_data()` is in **ingest_data.py**.

* Curvilinear and projected grids are classified from their auxiliary
  longitude/latitude cell centers, so blocks align with the common containers
  while retaining the native grid.

## Store data
Store blocks by spatial container.

## Aggregate data and containers
We want to have a spatio-temporal hierarchy of pre-aggregated values so we can answer questions faster. Because we want to keep datasets in their native resolutions, we will aggregate, coarsen, the data spatially by a factor of 2 and a factor of 4 (keeping each dataset in its projection), and coarsen the data to any higher temporal resolution out of {Hour, Day, Month, Year}. 

### Combined dataset

For each source dataset:

1. Compute a daily mean on its native grid.
2. Require sufficient cell-level temporal coverage:
   - hourly: at least 18 of 24 samples;
   - three-hourly, including WHOI: at least 6 of 8;
   - daily: one valid value.
3. Remap that daily field to the fixed ERA5 grid.
4. At every ERA5 cell/day, take the equal-weight mean of all valid remapped sources:

$\mathrm{Combined}_{j,t}=\frac{\sum_d m_{d,j,t}x_{d,j,t}}{\sum_d m_{d,j,t}}$

Thus:

- Three available sources with values $2,4,6$ produce `Combined = 4` and `source_count = 3`.
- One available source with value $5$ produces `Combined = 5` and `source_count = 1`.
- No available sources produce `NaN` and `source_count = 0`.

One important nuance: CARRA is currently remapped with **bilinear interpolation**. Its contribution is therefore interpolated from nearby CARRA grid centers; it is not an exact area-average of every CARRA cell intersecting the ERA5 cell. Conservative remapping could provide that behavior later.

The fixed base resolution is:

- Spatial: 0.25° ERA5 regular latitude–longitude grid.
- Temporal: one day.

It is not “0.25 Day”; these are separate spatial and temporal resolutions.

The downstream Combined hierarchy is:

```text
Combined
├── Daily
│   ├── 0.25° Source
│   ├── 0.5° ×2
│   └── 1.0° ×4
├── Monthly
│   ├── 0.25° Source
│   ├── 0.5° ×2
│   └── 1.0° ×4
└── Yearly
    ├── 0.25° Source
    ├── 0.5° ×2
    └── 1.0° ×4
```

Monthly and yearly values are calculated from Combined Daily, and their ×2/×4 products use the existing area-weighted spatial pipeline.

So the final domain is the union of valid source coverage **clipped to the canonical ERA5 target grid**. In the current files, that ERA5 grid covers 0–90°N, so datasets outside that target extent cannot extend Combined farther south.

Combined has ERA5’s spatial hierarchy, but not ERA5’s complete temporal hierarchy: Combined begins at Daily and therefore has Daily, Monthly, and Yearly—not Hourly or 3-hourly. Yearly output also requires a complete year; the current January-only data produces Daily and Monthly products but no Yearly product yet.

<!-- For configured compatible scalar variables, each source is first reduced to a
daily mean on its native grid. A source cell must meet the configured fraction
of its expected native samples; at the default 75%, hourly data needs 18 of 24
samples and three-hourly data (including WHOI) needs 6 of 8. Daily fields are
then remapped to the canonical standardized ERA5 grid and combined using the
configured source constants. Missing sources do not enter the denominator, so
one available source is retained outside overlap regions.

Each Combined field stores `source_count`, the number of valid datasets at
that target cell and day. Cached grid files retain centers, bounds/corners,
cell areas, CRS metadata, and a static domain mask. Cached xESMF weight files
and manifests are keyed by source-grid hash, target-grid hash, and remapping
method. The aligned source fields are not stored.

Combined is a native-daily dataset for the rest of ingestion. Monthly and
yearly products and the factor-2 and factor-4 spatial pyramids therefore use
the ordinary aggregation and block-writing paths.

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
Aggregate blocks also retain weighted sum, weight sum, valid count, minimum,
and maximum variables so query results can combine their values correctly.

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

``` -->
