from polaris.config import get_settings


def test_each_coarseness_factor_maps_to_its_spatial_level():
    settings = get_settings()

    assert {
        coarseness: spatial_level.name
        for coarseness, spatial_level in (
            settings.coarseness_to_spatial_level.items()
        )
    } == {
        1: "capacity_1",
        2: "capacity_2",
        4: "capacity_4",
    }


def test_mapped_spatial_levels_are_configured_schemes():
    settings = get_settings()

    for spatial_level in settings.coarseness_to_spatial_level.values():
        assert settings.container_schemes[spatial_level.name] is spatial_level


def test_combined_dataset_uses_daily_era5_grid_configuration():
    combined = get_settings().combined_dataset

    assert combined["dataset"] == "combined"
    assert combined["target_dataset"] == "era5_single_level"
    assert combined["temporal_resolution"] == "1D"
    assert combined["minimum_daily_coverage"] == 0.75
    assert combined["regridding_method"] == "bilinear"
