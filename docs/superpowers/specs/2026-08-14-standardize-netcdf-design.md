# Standardize and Consolidate NetCDF Files

## Goal

For each input CSV row, combine the JSON list in `file_paths` into one standardized NetCDF file and write a separate transformed metadata CSV.

## Data and naming contract

The input CSV remains unchanged. The transformed metadata is written to a separate CSV with `file_paths` renamed to `file_path` and a new `grid_type` column.

Every output dataset uses `timestamp` as its time dimension when a time coordinate is present.

Rectilinear geographic grids use `latitude` and `longitude` as dimensions and coordinates. Curvilinear geographic grids retain `y` and `x` as dimensions and use 2D `latitude(y, x)` and `longitude(y, x)` coordinates. The metadata records the effective dimension names so later code can select dimensions using `grid_type`.

## Processing flow

1. Parse each `file_paths` cell as a JSON list.
2. Open and combine the listed files with xarray.
3. Infer coordinate roles from CF metadata, units, axis attributes, and conservative name fallbacks.
4. Classify the grid as rectilinear, curvilinear, or another explicitly supported type.
5. Rename coordinates and dimensions to the standard contract.
6. Standardize 1D longitude values to `[0, 360)` and latitude ordering/range where applicable.
7. Save one uniquely named NetCDF per input row.
8. Build one transformed metadata row for each successful output.
9. Write the separate transformed metadata CSV only after all output NetCDF files have succeeded.
10. Delete the original source files only after the transformed metadata CSV has succeeded.

## Failure handling

An ambiguous coordinate or failed output raises an error and stops processing. Source files are not deleted unless every consolidated NetCDF and the transformed metadata CSV have been written successfully. Temporary output names should be used where practical to avoid leaving partial final files.

## Verification

Verify that each output NetCDF can be reopened, has the expected standardized dimensions/coordinates, and that the transformed CSV has one row per output file with valid paths and `grid_type` values.
