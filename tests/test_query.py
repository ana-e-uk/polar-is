from datetime import datetime

import pytest

from storage.query_data.query_data import (
    BoundingBox,
    QueryStorage,
    available_additional_parameters,
    available_datasets,
    available_variables,
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
