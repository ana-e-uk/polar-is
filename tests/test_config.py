from polaris.config import get_settings


def test_supported_coarseness_factors_are_reduced():
    assert get_settings().supported_coarseness_factors == (1, 2)


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
