# Managing Polar-is storage

The canonical geographic bucket grid in `config.yaml` is a lookup aid, not a
physical storage hierarchy. Each canonical data grid has one JSONL lookup mapping
bucket IDs to one or more rectangular grid windows.

Physical storage consists of:

- `catalogs/grids.jsonl` and reusable grid NetCDF files;
- `catalogs/datasets.jsonl` for dataset-variant metadata;
- `bucket_lookup/<grid_id>.jsonl` for spatial lookup;
- `products/.../*.nc` for time partitions;
- `metadata.jsonl` for the shared product index.

Catalog and partition identifiers are deterministic. Index paths are relative to
the storage root. Regeneration should be performed only after standardized inputs
and the xESMF-capable environment have been verified; remove the previous stored
data only after the replacement build validates successfully.
