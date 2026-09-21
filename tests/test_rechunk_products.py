import json
from types import SimpleNamespace

import numpy as np
import xarray as xr

from storage.manage.rechunk_products import rechunk_products


def test_rechunk_products_preserves_values_and_bounds_spatial_chunks(tmp_path):
    product_index = tmp_path / "metadata.jsonl"
    product_path = tmp_path / "products" / "source.nc"
    product_path.parent.mkdir()
    original = xr.Dataset({
        "value": (
            ("timestamp", "y", "x"),
            np.arange(2 * 32 * 64, dtype=np.float32).reshape(2, 32, 64),
        ),
    })
    original.to_netcdf(
        product_path,
        encoding={"value": {"chunksizes": (1, 32, 64)}},
    )
    product_index.write_text(json.dumps({
        "relative_path": "products/source.nc",
    }) + "\n")
    settings = SimpleNamespace(product_index=product_index)

    paths = rechunk_products(settings, target_chunk_bytes=16 * 1024)

    assert paths == (product_path,)
    with xr.open_dataset(product_path) as rewritten:
        xr.testing.assert_equal(rewritten, original)
        assert rewritten["value"].encoding["chunksizes"] == (2, 32, 64)
