# Querying data

The API and CLI pass the same query to `normalize_query()` before storage
planning. A normalized query describes the requested result; it does not need
to identify the repository or dataset that supplies the data.

## Required fields

- `variable`: one canonical variable from the values of the `variables`
  dictionaries in `config.yaml`.
- `region`: a bounding box with `west`, `east`, `south`, and `north`. Values are
  entered with longitudes from -180 to 180 and rounded to three decimal places.
  Normalized query longitudes use the storage convention from 0 to 360. An
  internal `west` greater than `east` therefore wraps through 360/0. The conversion
  and block overlap calculation is described in the **Longitude overlap** section below.
- `time_start` and `time_end`: `YYYY-MM`, `YYYY-MM-DD`, or `YYYY-MM-DDTHH`.
  Missing start components use the beginning of the selected period; missing
  end components use its end. Minutes and finer units are not accepted.
- `coarseness_factor`: a key from `coarseness_to_spatial_level` in
  `config.yaml`.
- `time_unit`: `Hour`, `Day`, `Month`, `Year`, or `Source`.
- `function`: an entry in `supported_query_functions` in `config.yaml`.
- `aggregation_method`: an entry in `function_aggregation_methods` in
  `config.yaml`.
- `predicate` and `filter_value`: required for `find-time` and `find-area`.
  Predicates are normalized to `lt`, `le`, `eq`, `ne`, `ge`, or `gt`.

## Optional filters

- `repository`: a repository in `name_docs`.
- `dataset`: a dataset in `name_docs`, restricted to `repository` when that
  filter is present.
- `additional_parameters`: dataset-specific parameter values from `name_docs`.
  A dataset must be selected before fixing these values.

Repository and dataset narrow the acceptable variable options. With neither
filter, variables are the union of the canonical variables from every dataset.

## Initial query plan

The requested data grid is `(coarseness_factor, time_unit)`. The planner maps
the coarseness factor through `coarseness_to_spatial_level`, then reads only
that spatial level's configured `metadata.jsonl` index. Later planning steps
calculate overlapping bucket IDs and apply one combined filter for bucket,
variable, data grid, optional source constraints, and time overlap. Candidate
blocks are then refined using their exact `block_summary` bounds and grouped by
repository, dataset, variable, and additional parameters.

Coverage is checked separately for every block group at the exact requested
data grid. It is stored as sparse hit and miss sets whose entries are
`(bucket_id, timestamp)`. A block marks timestamps from its inclusive
`time_start` through `time_end`. For now, any block-summary envelope that
overlaps the query counts as spatial coverage for that bucket; this does not
yet verify individual coordinates inside the NetCDF block. Missing cells and
the absence of exact-grid blocks produce warnings rather than resolution
fallbacks.

## Execution and results

The executor derives each selected block path from its spatial level,
`bucket_id`, and `block_id`. It slices time, masks the bounding box, and uses
`spatially_crop_block()` before loading the selected cells. Native blocks are
given the same aggregate statistics as pre-aggregated blocks when they are
opened.

Because stored curvilinear blocks do not retain global x/y indexes, cropped
blocks are combined using `timestamp` and a one-dimensional `cell` coordinate.
Latitude, longitude, bucket ID, and a stable coordinate-based cell ID remain
attached to every cell.

Each discovered block group produces a separate NetCDF file under
`storage/data/tmp/query_results/{query_id}/{function}/`. The returned
`QueryResult` also contains the in-memory Xarray datasets, source information,
units, block IDs, miss sets, and warnings. Mean results combine retained
statistics as `sum(weighted_sum) / sum(weight_sum)`; minimum and maximum use
the retained extrema.

## Example

```python
{
    "variable": "sea_surface_temperature",
    "region": {"west": -50.0, "east": 20.0, "south": 40.0, "north": 80.0},
    "time_start": "2020-01",
    "time_end": "2020-12",
    "coarseness_factor": 2,
    "time_unit": "Day",
    "function": "timeseries",
    "aggregation_method": "mean",
}
```

### Longitude overlap

The accepted longitude range is `[-180, 180]`:

```text
180°W       0°       180°E
 -180       0         180
```

`-180` and `180` are the same meridian. In the storage convention:

```text
0°          180°          360°
0            180            0
```

Negative longitudes are converted by adding 360:

```text
-180 → 180
 -70 → 290
 -20 → 340
   0 →   0
  30 →  30
 180 → 180
```

For example, consider a user query from 70°W to 30°E:

```python
west = -70
east = 30
```

After normalization:

```python
west = 290
east = 30
```

Because `290 > 30`, `_longitude_intervals()` splits it at the storage boundary:

```python
((290, 360), (0, 30))
```

Visually:

```text
Storage:  0────────30              290────────360
Query:    [included]               [included]
```

For `capacity_2`, the longitude buckets are:

```text
r*_c0:   0–120
r*_c1: 120–240
r*_c2: 240–360
```

Therefore, that query overlaps columns `c0` and `c2`, but not `c1`.

A query entirely within one side does not need splitting.

The special full-world input:

```python
west = -180
east = 180
```

becomes:

```python
west = 180
east = 180
```

The original validator prohibits a zero-width box, so this equality can only represent the complete 360-degree span. `_longitude_intervals()` therefore returns `(0, 360)`.

One current limitation is that a small user-entered box crossing the ±180° meridian, such as `west=170, east=-170`, is rejected because the input requires `west < east`.
