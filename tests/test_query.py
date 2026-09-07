from dataclasses import replace
from datetime import datetime
import json

import pytest

from polaris.config import ContainerScheme, get_settings
from storage.query_data.query_data import (
    BoundingBox,
    QueryStorage,
    RequestedDataGrid,
    available_additional_parameters,
    available_datasets,
    available_variables,
    plan_query,
    normalize_query,
)


def _query(**changes):
    query = {
        "variable": "sea_surface_temperature",
        "region": {
            "west": -50.12345,
            "east": 20.67891,
            "south": 40,
            "north": 80,
        },
        "time_start": "2020-02",
        "time_end": "2020-03",
        "coarseness_factor": 2,
        "time_unit": "Day",
        "function": "timeseries",
        "aggregation_method": "mean",
    }
    query.update(changes)
    return query


def test_normalizes_shared_query_without_source_filters():
    result = normalize_query(_query())

    assert result.variable == "sea_surface_temperature"
    assert result.region == BoundingBox(309.877, 20.679, 40.0, 80.0)
    assert result.time_start == datetime(2020, 2, 1, 0)
    assert result.time_end == datetime(2020, 3, 31, 23)
    assert result.coarseness_factor == 2
    assert result.time_unit == "Day"
    assert result.function == "timeseries"
    assert result.aggregation_method == "mean"
    assert result.repository is None
    assert result.dataset is None
    assert result.additional_parameters == {}


def test_query_longitudes_match_the_storage_convention():
    result = normalize_query(
        _query(
            region={"west": -180, "east": -20, "south": -10, "north": 10}
        )
    )

    assert result.region == BoundingBox(180.0, 340.0, -10.0, 10.0)


def test_query_storage_uses_the_normalized_query():
    storage = QueryStorage([], _query())

    assert storage.query.variable == "sea_surface_temperature"
    assert storage.query.coarseness_factor == 2
    assert storage.files_for_func_list == []


def test_plan_reads_only_the_requested_spatial_level(tmp_path):
    selected = ContainerScheme(
        name="capacity_2",
        factor=2,
        data_dir=tmp_path / "capacity_2",
        metadata=tmp_path / "capacity_2" / "metadata.jsonl",
        definitions=tmp_path / "capacity_2.json",
    )
    unselected = ContainerScheme(
        name="capacity_1",
        factor=1,
        data_dir=tmp_path / "capacity_1",
        metadata=tmp_path / "capacity_1" / "metadata.jsonl",
        definitions=tmp_path / "capacity_1.json",
    )
    selected.metadata.parent.mkdir()
    unselected.metadata.parent.mkdir()
    records = [{"block_id": "first"}, {"block_id": "second"}]
    selected.metadata.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n"
    )
    unselected.metadata.write_text("this index must not be read\n")
    settings = replace(
        get_settings(),
        container_schemes={
            "capacity_1": unselected,
            "capacity_2": selected,
        },
        coarseness_to_spatial_level={1: unselected, 2: selected},
    )

    plan = plan_query(_query(coarseness_factor=2), settings)

    assert plan.requested_data_grid == RequestedDataGrid(2, "Day")
    assert plan.spatial_level is selected
    assert plan.index_records == tuple(records)


def test_plan_filters_refines_and_groups_matching_blocks(tmp_path):
    selected = ContainerScheme(
        name="capacity_2",
        factor=2,
        data_dir=tmp_path / "capacity_2",
        metadata=tmp_path / "capacity_2" / "metadata.jsonl",
        definitions=tmp_path / "capacity_2.json",
    )
    selected.metadata.parent.mkdir()

    def record(block_id, **changes):
        value = {
            "repository": "copernicusclimatedatastore",
            "dataset": "carra_height",
            "variable": "sea_surface_temperature",
            "additional_parameters": {"height": "15m"},
            "bucket_id": "r1_c2",
            "coarseness_factor": 2,
            "temporal_resolution": "1D",
            "product_type": "aggregate",
            "time_start": "2020-01-01T00:00:00",
            "time_end": "2020-01-31T00:00:00",
            "block_summary": {
                "lon_min": 300.0,
                "lon_max": 310.0,
                "lat_min": 20.0,
                "lat_max": 25.0,
            },
            "block_id": block_id,
        }
        value.update(changes)
        return value

    records = [
        record("first"),
        record(
            "second",
            bucket_id="r2_c0",
            block_summary={
                "lon_min": 10.0,
                "lon_max": 20.0,
                "lat_min": 50.0,
                "lat_max": 60.0,
            },
        ),
        record("other-parameters", additional_parameters={"height": "30m"}),
        record(
            "other-source",
            repository="noaancei",
            dataset="emsst",
            additional_parameters={},
        ),
        record(
            "outside-exact-region",
            block_summary={
                "lon_min": 250.0,
                "lon_max": 260.0,
                "lat_min": 20.0,
                "lat_max": 25.0,
            },
        ),
        record("wrong-bucket", bucket_id="r1_c1"),
        record("wrong-variable", variable="air_temperature"),
        record("wrong-coarseness", coarseness_factor=4),
        record("wrong-time-unit", temporal_resolution="1MS"),
        record("wrong-time", time_start="2019-01-01", time_end="2019-01-31"),
    ]
    selected.metadata.write_text(
        "\n".join(json.dumps(item) for item in records) + "\n"
    )
    settings = replace(
        get_settings(),
        container_schemes={"capacity_2": selected},
        coarseness_to_spatial_level={2: selected},
    )
    query = _query(
        region={"west": -70, "east": 30, "south": 10, "north": 80},
        time_start="2020-01",
        time_end="2020-01",
    )

    plan = plan_query(query, settings)

    assert plan.overlapping_bucket_ids == (
        "r1_c0",
        "r1_c2",
        "r2_c0",
        "r2_c2",
    )
    assert {item["block_id"] for item in plan.matching_blocks} == {
        "first",
        "second",
        "other-parameters",
        "other-source",
    }
    assert len(plan.block_groups) == 3
    assert {
        (group.repository, group.dataset) for group in plan.block_groups
    } == {
        ("copernicusclimatedatastore", "carra_height"),
        ("noaancei", "emsst"),
    }

    filtered_plan = plan_query(
        {
            **query,
            "repository": "copernicusclimatedatastore",
            "dataset": "carra_height",
            "additional_parameters": {"height": "15m"},
        },
        settings,
    )
    assert {item["block_id"] for item in filtered_plan.matching_blocks} == {
        "first",
        "second",
    }


def test_source_filters_and_dataset_parameters_are_validated():
    result = normalize_query(
        _query(
            repository="copernicusclimatedatastore",
            dataset="carra_height",
            additional_parameters={"height": "15m"},
        )
    )

    assert result.repository == "copernicusclimatedatastore"
    assert result.dataset == "carra_height"
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
    ) == {"height": ("15m", "30m")}


def test_additional_parameters_require_a_dataset():
    with pytest.raises(ValueError, match="dataset is required"):
        normalize_query(_query(additional_parameters={"height": "15m"}))


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


def test_repository_and_dataset_restrict_the_variable():
    with pytest.raises(ValueError, match="Unsupported variable"):
        normalize_query(
            _query(
                repository="nasaearthdata",
                variable="sea_surface_temperature",
            )
        )
