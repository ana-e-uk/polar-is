# Querying Polar-is storage

Queries are required to provide an exact `time_unit` and `coarseness_factor`. Supported time units are Source, Hour, Day, Month, and Year, and supported coarseness factors are configured explicitly.

The query planner reads three resources:

- the dataset catalog for repository, dataset, variable, and parameters;
- the shared product index for time partitions and grid windows;
- the selected grid's bucket lookup for spatial window candidates.

It filters partitions by the requested dataset identity, product, time interval,
and intersecting grid windows, then reports sparse bucket/time coverage.

The query executor opens the canonical grid once per result group and reads only the
selected time partitions and `y/x` slices. It applies the exact geographic mask,
combines sufficient statistics, and returns structured
`timestamp/grid_y/grid_x` results. Results carry `grid_id`, the global grid
window, and partition IDs to make joining different partitions possible. For example, heatmap JSON uses grid-axis indices and two-dimensional
center coordinates.
