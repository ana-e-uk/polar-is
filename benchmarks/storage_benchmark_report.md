# Polar-is storage benchmark

Run: 2026-09-21T18:41:49-05:00

Times are backend-only wall times. Each scenario/version used one persistent, newly started process: first query = cold-ish, second = untimed warm-up, followed by three measured warm queries. Old and redesigned calls were alternated. Peak RSS covers that scenario process, including its API check.

| Scenario | Old cold-ish | New cold-ish | Old warm median | New warm median | Warm speedup | Old plan | New plan | Old execute/write | New execute/write | Old peak RSS | New peak RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ERA5 Source (1H) timeseries, small, 2 days | 0.491 s | 0.390 s | 0.164 s | 0.065 s | 2.52× | 0.003 s | 0.000 s | 0.161 s | 0.065 s | 222.8 MiB | 238.9 MiB |
| EMSST Source (1D) timeseries, small, 2 days | 0.506 s | 0.383 s | 0.193 s | 0.054 s | 3.60× | 0.003 s | 0.000 s | 0.191 s | 0.053 s | 183.3 MiB | 266.2 MiB |
| Multi-dataset Day heatmap, small | 1.466 s | 0.717 s | 1.146 s | 0.352 s | 3.25× | 0.003 s | 0.000 s | 1.143 s | 0.352 s | 338.4 MiB | 375.8 MiB |
| Multi-dataset Day heatmap, broad | 9.644 s | 2.441 s | 9.307 s | 2.200 s | 4.23× | 0.005 s | 0.001 s | 9.302 s | 2.199 s | 2.6 GiB | 742.4 MiB |
| Month, coarsen-2 heatmap, broad | 2.981 s | 0.915 s | 2.583 s | 0.449 s | 5.75× | 0.001 s | 0.000 s | 2.582 s | 0.448 s | 962.9 MiB | 374.6 MiB |

## Correctness and output

| Scenario | Version | Groups | Timestamps | Spatial cells | Valid values | Result size | Datasets | API end-to-end |
|---|---|---:|---:|---:|---:|---:|---|---:|
| ERA5 Source (1H) timeseries, small, 2 days | old | 1 | 48 | 0 | 48 | 18.7 KiB | era5_single_level | 0.207 s (completed) |
| ERA5 Source (1H) timeseries, small, 2 days | redesigned | 1 | 48 | 0 | 48 | 19.0 KiB | era5_single_level | 0.092 s (completed) |
| EMSST Source (1D) timeseries, small, 2 days | old | 1 | 2 | 0 | 2 | 12.6 KiB | emsst | 0.249 s (completed) |
| EMSST Source (1D) timeseries, small, 2 days | redesigned | 1 | 2 | 0 | 2 | 13.7 KiB | emsst | 0.078 s (completed) |
| Multi-dataset Day heatmap, small | old | 4 | 0 | 2324 | 2324 | 784.2 KiB | carra_height, emsst, era5_single_level, combined | 1.383 s (completed) |
| Multi-dataset Day heatmap, small | redesigned | 4 | 0 | 4490 | 2324 | 195.0 KiB | carra_height, era5_single_level, combined, whoi_cdr | 0.446 s (completed) |
| Multi-dataset Day heatmap, broad | old | 4 | 0 | 750269 | 750269 | 209.5 MiB | carra_height, emsst, era5_single_level, combined | 0.017 s (HTTP 422) |
| Multi-dataset Day heatmap, broad | redesigned | 4 | 0 | 1340481 | 723260 | 22.3 MiB | carra_height, era5_single_level, combined, whoi_cdr | 0.015 s (HTTP 422) |
| Month, coarsen-2 heatmap, broad | old | 4 | 0 | 190718 | 190718 | 53.3 MiB | carra_height, emsst, era5_single_level, combined | 0.013 s (HTTP 422) |
| Month, coarsen-2 heatmap, broad | redesigned | 5 | 0 | 387765 | 195072 | 6.1 MiB | carra_height, emsst, era5_single_level, combined, whoi_cdr | 0.012 s (HTTP 422) |

## Storage inventory

| Version | Managed size | Total data directory | Managed files | Product files | Grid files | Lookup files | Metadata files | Metadata records |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| old | 15.1 GiB | 33.1 GiB | 342 | 336 | 0 | 0 | 3 | 336 |
| redesigned | 1.3 GiB | 1.5 GiB | 26 | 18 | 3 | 3 | 3 | 26 |

## Interpretation notes

- ERA5 native hourly is queried as `Hour` in old storage and `Source` in redesigned storage.
- EMSST native daily is queried as `Day` in old storage and `Source` in redesigned storage.
- Literal multi-dataset `Day` queries can have different group counts: old treats native daily as Day, while redesigned uses Day only for a product derived from finer source cadence.
- Managed size excludes downloads, standardized inputs, query outputs, caches, and backups. Total data-directory size includes them.
- Cold-ish measurements use a newly started Python process but do not clear the macOS filesystem cache.
