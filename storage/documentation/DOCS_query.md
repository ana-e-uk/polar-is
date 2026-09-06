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
  internal `west` greater than `east` therefore wraps through 360/0.
- `time_start` and `time_end`: `YYYY-MM`, `YYYY-MM-DD`, or `YYYY-MM-DDTHH`.
  Missing start components use the beginning of the selected period; missing
  end components use its end. Minutes and finer units are not accepted.
- `coarseness_factor`: a key from `coarseness_to_spatial_level` in
  `config.yaml`.
- `time_unit`: `Hour`, `Day`, `Month`, `Year`, or `Source`.
- `function`: an entry in `supported_query_functions` in `config.yaml`.
- `aggregation_method`: an entry in `function_aggregation_methods` in
  `config.yaml`.

## Optional filters

- `repository`: a repository in `name_docs`.
- `dataset`: a dataset in `name_docs`, restricted to `repository` when that
  filter is present.
- `additional_parameters`: dataset-specific parameter values from `name_docs`.
  A dataset must be selected before fixing these values.

Repository and dataset narrow the acceptable variable options. With neither
filter, variables are the union of the canonical variables from every dataset.

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
