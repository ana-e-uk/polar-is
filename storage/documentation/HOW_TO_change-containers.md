# Changing geographic buckets

Buckets are used only to narrow spatial searches. Edit `container_grid` in
`config.yaml` to change its origin or latitude/longitude sizes. The sizes must
divide the global longitude and latitude spans exactly.

After changing the bucket grid, regenerate every file under
`storage/data/bucket_lookup`. Product files, canonical grids, and product IDs do
not depend on bucket size and do not need to be rewritten.
