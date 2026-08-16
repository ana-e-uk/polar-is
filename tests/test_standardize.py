"""End-to-end check of the NetCDF standardization pipeline.

This script uses hard links in a temporary directory because ``standardize``
deletes its source files after successfully creating the consolidated output.
This leaves the real files listed in downloaded_data.jsonl untouched.
"""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

import xarray as xr


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from polaris.config import get_settings  # noqa: E402
from storage.ingest_data.standardize import (  # noqa: E402
    _coord_role,
    read_metadata,
    standardize,
)


def time_coordinate_name(dataset: xr.Dataset) -> str:
    """Return the source coordinate that represents time."""

    matches = [
        name
        for name, coordinate in dataset.coords.items()
        if _coord_role(name, coordinate) == "time"
    ]
    assert len(matches) == 1, f"Expected one time coordinate, found {matches}"
    return matches[0]


def expected_timestamp_count(records: list[dict]) -> list[int]:
    """Validate non-overlapping inputs and return expected output sizes."""

    counts = []
    for record in records:
        all_timestamps = []
        for raw_path in record["file_paths"]:
            with xr.open_dataset(PROJECT_ROOT / raw_path) as dataset:
                time_name = time_coordinate_name(dataset)
                all_timestamps.extend(dataset[time_name].values.tolist())

        assert len(all_timestamps) == len(set(all_timestamps)), (
            "Input files contain overlapping timestamps, so they cannot test "
            "concatenation by adjacent coordinates"
        )
        assert all_timestamps == sorted(all_timestamps), (
            "Input files are not ordered chronologically"
        )
        counts.append(len(all_timestamps))

    return counts


def temporary_input_records(
    records: list[dict], temporary_root: Path
) -> list[dict]:
    """Point copied metadata at temporary hard links to the source data."""

    test_records = deepcopy(records)
    for record_number, record in enumerate(test_records):
        record_dir = temporary_root / f"record_{record_number}"
        record_dir.mkdir()
        temporary_paths = []

        for raw_path in record["file_paths"]:
            source = (PROJECT_ROOT / raw_path).resolve()
            assert source.is_file(), f"Missing source file: {source}"
            temporary_path = record_dir / source.name
            os.link(source, temporary_path)
            temporary_paths.append(str(temporary_path))

        record["file_paths"] = temporary_paths

    return test_records


def main() -> None:
    settings = get_settings()
    records = read_metadata(settings.downloaded_data_)
    assert records, f"No records found in {settings.downloaded_data_}"

    expected_counts = expected_timestamp_count(records)
    output_dir = settings._standardized
    metadata_output = settings.standardized_data_
    assert metadata_output.parent.resolve() == output_dir.resolve()
    assert metadata_output.name == "standardized_metadata.jsonl"

    temporary_parent = settings._data / "tmp"
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix="standardize-test-input-", dir=temporary_parent
    ) as temporary_directory:
        test_records = temporary_input_records(
            records, Path(temporary_directory)
        )
        standardize(test_records, output_dir, metadata_output)

    standardized_records = read_metadata(metadata_output)
    assert len(standardized_records) == len(records)

    for source_record, standardized_record, expected_count in zip(
        records, standardized_records, expected_counts, strict=True
    ):
        assert "file_paths" not in standardized_record
        assert standardized_record["grid_type"] == "curvilinear"
        assert standardized_record["dataset"] == source_record["dataset"]

        output_path = Path(standardized_record["file_path"])
        assert output_path.is_file(), f"Missing output file: {output_path}"
        assert output_path.parent.resolve() == output_dir.resolve()

        with xr.open_dataset(output_path) as dataset:
            assert {"timestamp", "y", "x"}.issubset(dataset.dims)
            assert "valid_time" not in dataset.dims
            assert dataset.sizes["timestamp"] == expected_count
            assert dataset["latitude"].dims == ("y", "x")
            assert dataset["longitude"].dims == ("y", "x")

        print(f"PASS: combined {expected_count} timestamps into {output_path}")

    print(f"PASS: wrote metadata to {metadata_output}")


if __name__ == "__main__":
    main()
