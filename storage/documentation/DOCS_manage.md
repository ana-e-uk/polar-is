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

Every block record uses metadata schema version 3 and contains the source
dataset fields plus:

- `spatial_level`, `bucket_code`, and `bucket_id`
- `block_id` and `product_type`
- native and resulting temporal/spatial resolutions
- `coarseness_factor`
- temporal and spatial aggregation methods
- aggregation order/version
- `block_summary` with cell-center bounds and scientific-variable extrema

Block paths are derived from the spatial level, bucket ID, and block ID.
Bucket codes and IDs are local to a spatial level. The composite
`(spatial_level, bucket_code)` is the globally meaningful bucket identity.
