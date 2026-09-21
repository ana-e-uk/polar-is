import json
from types import SimpleNamespace

import numpy as np
import xarray as xr

from storage.grid_topology import canonical_grid_id
from storage.manage.migrate_grid_identity import migrate_grid_identity


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def test_migration_deduplicates_grids_that_only_differ_in_labels(tmp_path):
    grids_dir = tmp_path / "catalogs" / "grids"
    lookups_dir = tmp_path / "bucket_lookup"
    grids_dir.mkdir(parents=True)
    lookups_dir.mkdir()
    base = xr.Dataset(
        {"cell_area": (("y", "x"), np.ones((1, 2)))},
        coords={"latitude": ("y", [10.0]), "longitude": ("x", [20.0, 21.0])},
        attrs={"grid_type": "rectilinear"},
    )
    labeled = base.copy(deep=True)
    labeled["latitude"].attrs["source"] = "another provider"
    for old_id, grid in (("a" * 32, base), ("b" * 32, labeled)):
        grid.to_netcdf(grids_dir / f"{old_id}.nc")
        _write_jsonl(lookups_dir / f"{old_id}.jsonl", [])
    catalog = tmp_path / "catalogs" / "grids.jsonl"
    _write_jsonl(catalog, [
        {"grid_id": old_id, "grid_type": "rectilinear", "shape_y": 1,
         "shape_x": 2, "relative_path": f"catalogs/grids/{old_id}.nc"}
        for old_id in ("a" * 32, "b" * 32)
    ])
    product = tmp_path / "products" / "source.nc"
    product.parent.mkdir()
    xr.Dataset({"value": (("timestamp", "y", "x"), [[[1.0, 2.0]]])},
               attrs={"grid_id": "b" * 32}).to_netcdf(product)
    index = tmp_path / "metadata.jsonl"
    _write_jsonl(index, [{"grid_id": "b" * 32, "relative_path": "products/source.nc"}])
    settings = SimpleNamespace(
        grids_dir=grids_dir,
        grids_catalog=catalog,
        bucket_lookup_dir=lookups_dir,
        product_index=index,
        container_grid={"lon_min": 0, "lat_min": -90, "lon_size": 60, "lat_size": 30},
    )

    mapping = migrate_grid_identity(settings)

    new_id = canonical_grid_id(base)
    assert set(mapping.values()) == {new_id}
    assert len(catalog.read_text().splitlines()) == 1
    assert len(list(grids_dir.glob("*.nc"))) == 1
    assert len(list(lookups_dir.glob("*.jsonl"))) == 1
    assert json.loads(index.read_text())["grid_id"] == new_id
    with xr.open_dataset(product) as rewritten:
        assert rewritten.attrs["grid_id"] == new_id
