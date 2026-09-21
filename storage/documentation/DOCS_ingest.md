# Ingesting data into Polar-is

The ingestion pipeline has three steps:

1. Standardize downloaded source files with `python -m storage.ingest_data.standardize`.
2. Build the optional daily Combined dataset and all configured products with
   `python -m storage.ingest_data.aggregate_data`.
3. Query the resulting catalogs and product partitions.

Standardization normalizes dimensions to `timestamp`, `y`, and `x`; normalizes
latitude and longitude; records rectilinear bounds or projected CF geometry; and
moves meaningful singleton source coordinates into dataset metadata. It does not
attach per-cell IDs or storage indices.

## Catalogs and products

Each canonical native grid is written once under `storage/data/catalogs/grids`.
The grid catalog assigns it a deterministic 128-bit `grid_id`. A per-grid bucket
lookup maps the shared geographic buckets to rectangular windows on that grid.

Dataset metadata is written once to the dataset catalog. Product data is split by
time only: Source, Hour, and Day use monthly files; Month and Year use yearly
files. The shared product index stores relative paths, time ranges, coarseness,
`grid_id`, and the partition's global grid window.

Source products retain the source scientific variable. Derived products store
only weighted sum, weight sum, minimum, and maximum; coordinates, bounds, cell
areas, and topology come from the grid catalog. Files target roughly 64 MiB
chunks.

The product policy is centralized in `aggregate_data.product_policy`: Source is
retained at factor 1, eligible temporal products are strictly coarser than the
source cadence, and factor 2 exists only for Month and Year. Native three-hourly
data remains Source and weekly source data is rejected until calendar-boundary
weighting is specified.

## Combined dataset

Combined first calculates daily source means with the configured coverage
threshold, remaps those means to the canonical ERA5 grid, and computes an
available-source weighted mean. Grid geometry is shared through the grid catalog;
only xESMF weight operators are cached separately. Combined materializes Day at
factor 1 and Month/Year at factors 1 and 2. Its products retain a compact
`source_count` provenance variable.
