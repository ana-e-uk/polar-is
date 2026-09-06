import json

from polaris.config import ContainerScheme
from storage.ingest_data.make_data_blocks import block_path
from storage.manage.migrate_storage_schema_v3 import migrate_scheme


def test_migration_renames_block_and_removes_stored_path(tmp_path):
    scheme = ContainerScheme(
        "capacity_1",
        1,
        tmp_path / "capacity_1",
        tmp_path / "capacity_1" / "metadata.jsonl",
        tmp_path / "capacity_1.json",
    )
    old_path = scheme.data_dir / "r0_c0" / "old-name.nc"
    old_path.parent.mkdir(parents=True)
    old_path.touch()
    scheme.definitions.write_text(
        json.dumps({"r0_c0": {"data": 1}})
    )
    record = {
        "repository": "test",
        "dataset": "test",
        "variable": "value",
        "additional_params": None,
        "container": "capacity_1",
        "container_code": 0,
        "container_id": "r0_c0",
        "spatial_coarsening_factor": 1,
        "temporal_resolution": "D",
        "native_temporal_resolution": "D",
        "time_start": "2020-01-01T00:00:00.000000000",
        "time_end": "2020-01-02T00:00:00.000000000",
        "product_type": "native",
        "product_id": "old-id",
        "file_path": str(old_path),
        "block_summary": {"var_min": 1.0, "var_max": 2.0},
    }
    scheme.metadata.write_text(json.dumps(record) + "\n")

    assert migrate_scheme(scheme) == 1
    migrated = json.loads(scheme.metadata.read_text())
    path = block_path(scheme, migrated["bucket_id"], migrated["block_id"])

    assert path.is_file()
    assert not old_path.exists()
    assert "file_path" not in migrated
    assert "product_id" not in migrated
    assert migrated["temporal_resolution"] == "1D"
    assert migrated["time_start"] == "2020-01-01T00:00:00"
