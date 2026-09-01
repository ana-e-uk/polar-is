# Changing spatial containers

Capacity 1 is defined by `container_grid` in `config.yaml`. Its positive,
finite `lon_size` and `lat_size` values must divide 360 and 180 exactly, and
`lat_min` must remain -90.

Every entry in `container_schemes` supplies an integer factor and paths. The
factor-2 and factor-4 definitions are derived from capacity 1; do not specify
their bounds separately.

After changing the grid, regenerate/validate definitions with:

```shell
python -m storage.manage.space_containers
```

Previously ingested blocks must be regenerated because their cell-center
classifications and product identities belong to the old definitions.
