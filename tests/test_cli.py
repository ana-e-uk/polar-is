from api.command_line.data_object import DataObject


def test_data_object_builds_current_query_shape():
    obj = DataObject(
        name="sst",
        repository="noaancei",
        dataset="emsst",
        variable="sea_surface_temperature",
        time_start="2020-01-01",
        time_end="2020-01-02",
        time_unit="Day",
        south=0,
        north=20,
        west=0,
        east=40,
        coarseness_factor=1,
        aggregation_method="mean",
    )

    assert obj.query("find_area", predicate=">", filter_value=281) == {
        "repository": "noaancei",
        "dataset": "emsst",
        "variable": "sea_surface_temperature",
        "region": {"west": 0, "east": 40, "south": 0, "north": 20},
        "time_start": "2020-01-01",
        "time_end": "2020-01-02",
        "time_unit": "Day",
        "coarseness_factor": 1,
        "function": "find-area",
        "aggregation_method": "mean",
        "additional_parameters": {},
        "predicate": ">",
        "filter_value": 281,
    }
