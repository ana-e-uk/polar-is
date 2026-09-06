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
