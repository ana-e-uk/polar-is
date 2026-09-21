from dataclasses import replace
from datetime import datetime
import json

import pytest

from polaris.config import get_settings
from storage.query_data.query_data import (
    BoundingBox,
    RequestedDataGrid,
    available_additional_parameters,
    available_datasets,
    available_variables,
    normalize_query,
    plan_query,
)


GRID_ID = "0123456789abcdef0123456789abcdef"
VARIANT_ID = "fedcba9876543210fedcba9876543210"


def _query(**changes):
    query = {
        "variable": "sea_surface_temperature",
        "region": {"west": -50.12345, "east": 20.67891, "south": 40, "north": 80},
        "time_start": "2020-02",
        "time_end": "2020-03",
        "coarseness_factor": 2,
        "time_unit": "Month",
        "function": "timeseries",
        "aggregation_method": "mean",
    }
    query.update(changes)
    return query


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def _settings(tmp_path, records):
    settings = replace(
        get_settings(),
        product_index=tmp_path / "metadata.jsonl",
        datasets_catalog=tmp_path / "catalogs" / "datasets.jsonl",
        bucket_lookup_dir=tmp_path / "bucket_lookup",
    )
    _write_jsonl(settings.product_index, records)
    _write_jsonl(
        settings.datasets_catalog,
        [
            {
                "dataset_variant_id": VARIANT_ID,
                "repository": "copernicusclimatedatastore",
                "dataset": "carra_height",
                "additional_parameters": {"height": "15m"},
                "variables": {
                    "sea_surface_temperature": {
                        "units": "K",
                        "source_temporal_resolution": "3H",
                    }
                },
            }
        ],
    )
    _write_jsonl(
        settings.bucket_lookup_dir / f"{GRID_ID}.jsonl",
        [
            {
                "grid_id": GRID_ID,
                "bucket_id": "r4_c5",
                "grid_y_start": 0,
                "grid_y_stop": 20,
                "grid_x_start": 0,
                "grid_x_stop": 30,
            },
            {
                "grid_id": GRID_ID,
                "bucket_id": "r5_c0",
                "grid_y_start": 10,
                "grid_y_stop": 30,
                "grid_x_start": 20,
                "grid_x_stop": 40,
            },
        ],
    )
    return settings


def _partition(**changes):
    record = {
        "partition_id": "11111111111111111111111111111111",
        "dataset_variant_id": VARIANT_ID,
        "variable": "sea_surface_temperature",
        "grid_id": GRID_ID,
        "temporal_resolution": "Month",
        "coarseness_factor": 2,
        "time_start": "2020-01-01T00:00:00",
        "time_end": "2020-03-01T00:00:00",
        "grid_y_start": 0,
        "grid_y_stop": 30,
        "grid_x_start": 0,
        "grid_x_stop": 40,
        "relative_path": "products/example.nc",
    }
    record.update(changes)
    return record


def test_normalizes_shared_query_without_source_filters():
    result = normalize_query(_query())
    assert result.variable == "sea_surface_temperature"
    assert result.region == BoundingBox(309.877, 20.679, 40.0, 80.0)
    assert result.time_start == datetime(2020, 2, 1, 0)
    assert result.time_end == datetime(2020, 3, 31, 23)
    assert result.coarseness_factor == 2
    assert result.time_unit == "Month"
    assert result.repository is None


def test_find_query_normalizes_and_requires_predicate():
    result = normalize_query(
        _query(function="find-time", predicate=">", filter_value="10.5")
    )
    assert result.predicate == "gt"
    assert result.filter_value == 10.5
    with pytest.raises(ValueError, match="require a supported predicate"):
        normalize_query(_query(function="find-area"))


def test_planner_uses_shared_index_catalog_and_grid_lookup(tmp_path):
    settings = _settings(tmp_path, [_partition()])
    plan = plan_query(
        _query(
            repository="copernicusclimatedatastore",
            dataset="carra_height",
            additional_parameters={"height": "15m"},
        ),
        settings,
    )

    assert plan.requested_data_grid == RequestedDataGrid(2, "Month")
    assert len(plan.matching_blocks) == 1
    assert plan.matching_blocks[0]["partition_id"] == (
        "11111111111111111111111111111111"
    )
    assert plan.block_groups[0].grid_id == GRID_ID
    assert plan.block_groups[0].grid_window == (0, 30, 0, 40)
    assert "block_summary" not in plan.matching_blocks[0]


def test_planner_requires_exact_product_and_reports_no_match(tmp_path):
    settings = _settings(tmp_path, [_partition()])
    plan = plan_query(_query(time_unit="Day", coarseness_factor=1), settings)
    assert plan.matching_blocks == ()
    assert plan.coverage.warnings == (
        "No matching product partitions exist at the exact requested grid.",
    )


def test_source_filters_and_dataset_parameters_are_validated():
    result = normalize_query(
        _query(
            repository="copernicusclimatedatastore",
            dataset="carra_height",
            additional_parameters={"height": "15m"},
        )
    )
    assert result.additional_parameters == {"height": "15m"}
    assert available_datasets(result.repository) == (
        "carra_height",
        "era5_single_level",
    )
    assert available_variables(result.repository, result.dataset) == (
        "sea_surface_temperature",
    )
    assert available_additional_parameters(
        result.dataset, result.repository
    ) == {"height": ("15m", "30m"), "region": ("east", "west")}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"variable": ["sea_surface_temperature"]}, "Unsupported variable"),
        ({"coarseness_factor": 3}, "Unsupported coarseness factor"),
        ({"time_unit": "Minute"}, "Unsupported time unit"),
        ({"function": "histogram"}, "Unsupported function"),
        ({"aggregation_method": "median"}, "Unsupported aggregation method"),
        ({"time_start": "2020-02-01T00:30"}, "time_start must be"),
    ],
)
def test_rejects_unsupported_query_values(change, message):
    with pytest.raises(ValueError, match=message):
        normalize_query(_query(**change))
