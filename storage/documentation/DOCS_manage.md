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

Every block record uses metadata schema version 2 and contains the source
dataset fields plus:

- `container`, `container_code`, and `container_id`
- `block_id` and `product_type`
- native and resulting temporal/spatial resolutions
- `spatial_coarsening_factor`
- temporal and spatial aggregation methods
- aggregation order/version and source paths
- `block_summary` with cell-center bounds and scientific-variable extrema
- `file_path`

Container codes and IDs are local to a capacity. The composite
`(container, container_code)` is the globally meaningful identity.
