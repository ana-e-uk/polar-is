from polaris.config import get_settings


def test_supported_coarseness_factors_are_reduced():
    assert get_settings().supported_coarseness_factors == (1, 2)


def test_query_log_is_shared_storage_data():
    assert get_settings().query_log.name == "query_log.jsonl"
    assert get_settings().query_log.parent.name == "data"


def test_combined_dataset_uses_daily_era5_grid_configuration():
    combined = get_settings().combined_dataset

    assert combined["dataset"] == "combined"
    assert combined["target_dataset"] == "era5_single_level"
    assert combined["temporal_resolution"] == "1D"
    assert combined["minimum_daily_coverage"] == 0.75
    assert combined["regridding_method"] == "bilinear"


def test_frontend_titles_are_loaded_from_configuration():
    titles = get_settings().frontend_titles

    assert titles["repository"]["copernicusclimatedatastore"] == (
        "Copernicus Climate Data Store"
    )
    assert titles["variable"]["sea_surface_temperature"] == (
        "Sea Surface Temperature"
    )
    assert titles["resolution"]["0.25"]["coarsen-2"] == [0.5]
    assert "coarsen-4" not in titles["resolution"]["0.25"]


def test_era5_ingest_variables_have_expected_aggregation_methods():
    settings = get_settings()
    variables = settings.name_docs["copernicusclimatedatastore"][
        "era5_single_level"
    ]["variables"]

    mean_variables = {
        "2m_temperature",
        "ice_temperature_layer_1",
        "ice_temperature_layer_2",
        "ice_temperature_layer_3",
        "ice_temperature_layer_4",
        "snow_depth",
        "surface_pressure",
        "temperature_of_snow_layer",
    }
    sum_variables = {
        "snowfall",
        "snowmelt",
        "total_precipitation",
    }

    for variable in mean_variables | sum_variables:
        assert variables[variable] == variable
        assert settings.aggregation_methods[variable]["spatial"] == "mean"

    for variable in mean_variables:
        assert settings.aggregation_methods[variable]["temporal"] == "mean"

    for variable in sum_variables:
        assert settings.aggregation_methods[variable]["temporal"] == "sum"
