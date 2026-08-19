# Defining buckets

Buckets are defined by the `bucket_grid` parameter in **config.yaml**. The values `lon_min, lon_size, lat_size` must be defined.

## Requirements

**space_buckets.py** reads them in and makes sure they are valid:

* Bucket sizes must be positive, finite, and divide 360 and 180 exactly
* `lat_min`: must remain -90 to cover the Earth
* Longitude normalization is determined by the configured `lon_min`


The script also makes sure:
* Exact 90 degree latitude maps to the final row
* Block bounding rectangles use the configured longitude range

## Changing buckets

Bucket configuration steps:

1. Change `lon_min, lon_size, lat_size` in **config.yaml**
2. Regenerate **buckets.json**:
        
        python -m storage.manage.space_buckets

3. Begin ingesting data. Any data ingested before must be re-ingested to match the new buckets.