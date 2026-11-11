import json
from pathlib import Path

import pytest

from storage.catalog import (
    BucketWindowRecord,
    DatasetCatalogRecord,
    GridCatalogRecord,
    ProductIndexRecord,
)


GRID_ID = "0123456789abcdef0123456789abcdef"
PARTITION_ID = "fedcba9876543210fedcba9876543210"


def product_record(**changes) -> ProductIndexRecord:
    values = {
        "partition_id": PARTITION_ID,
        "dataset_variant_id": "era5",
        "variable": "sea_surface_temperature",
        "grid_id": GRID_ID,
        "temporal_resolution": "1D",
        "coarseness_factor": 1,
        "time_start": "2018-01-01T00:00:00",
        "time_end": "2018-01-31T00:00:00",
        "grid_y_start": 0,
        "grid_y_stop": 100,
        "grid_x_start": 0,
        "grid_x_stop": 200,
        "relative_path": "products/era5/sst/2018-01.nc",
    }
    values.update(changes)
    return ProductIndexRecord(**values)


def test_catalog_records_round_trip_through_json():
    records = [
        GridCatalogRecord(
            grid_id=GRID_ID,
            grid_type="rectilinear",
            shape_y=100,
            shape_x=200,
            relative_path=f"catalogs/grids/{GRID_ID}.nc",
        ),
        DatasetCatalogRecord(
            dataset_variant_id="carra-15m",
            repository="copernicusclimatedatastore",
            dataset="carra_height",
            additional_parameters={"height": "15m"},
            variables={
                "sea_surface_temperature": {
                    "units": "K",
                    "display_name": "Sea Surface Temperature",
                }
            },
        ),
        product_record(),
        BucketWindowRecord(
            grid_id=GRID_ID,
            bucket_id="N30_E000",
            grid_y_start=20,
            grid_y_stop=40,
            grid_x_start=50,
            grid_x_stop=80,
        ),
    ]

    for record in records:
        encoded = json.loads(json.dumps(record.to_dict()))
        assert type(record).from_dict(encoded) == record


def test_cropped_products_from_the_same_grid_keep_the_same_grid_id():
    first = product_record(
        partition_id="11111111111111111111111111111111",
        grid_x_start=0,
        grid_x_stop=100,
    )
    second = product_record(
        partition_id="22222222222222222222222222222222",
        grid_x_start=100,
        grid_x_stop=200,
    )

    assert first.grid_id == second.grid_id == GRID_ID
    assert first.grid_x_stop == second.grid_x_start


def test_product_index_contains_no_per_cell_or_singleton_coordinates():
    fields = product_record().to_dict()

    assert "number" not in fields
    assert "cell_id" not in fields
    assert "bucket_id" not in fields
    assert "grid_y_index" not in fields
    assert "grid_x_index" not in fields


def test_product_paths_are_relative_and_resolved_from_storage_root():
    record = product_record()

    assert record.resolved_path(Path("/store")) == Path(
        "/store/products/era5/sst/2018-01.nc"
    )
    with pytest.raises(ValueError, match="relative path"):
        product_record(relative_path="/absolute/product.nc")


def test_windows_must_be_nonempty():
    with pytest.raises(ValueError, match="stops must be greater"):
        product_record(grid_y_start=10, grid_y_stop=10)


def test_grid_and_partition_ids_are_128_bit_hexadecimal_values():
    with pytest.raises(ValueError, match="128-bit hexadecimal"):
        product_record(grid_id="grid-a")
    with pytest.raises(ValueError, match="128-bit hexadecimal"):
        product_record(partition_id="partition-a")
