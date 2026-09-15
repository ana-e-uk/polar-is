from dataclasses import replace
import json

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd
import xarray as xr

from api.interface.app import api_settings, app
from polaris.config import ContainerScheme, get_settings
from storage.ingest_data.aggregate_data import add_aggregate_statistics
from storage.ingest_data.make_data_blocks import block_path


def _settings(tmp_path):
    scheme = ContainerScheme(
        name="capacity_1",
        factor=1,
        data_dir=tmp_path / "capacity_1",
        metadata=tmp_path / "capacity_1" / "metadata.jsonl",
        definitions=tmp_path / "capacity_1.json",
    )
    data = xr.Dataset(
        {
            "sea_surface_temperature": (
                ("timestamp", "y", "x"),
                np.asarray([280.0, 282.0]).reshape(2, 1, 1),
                {"units": "K"},
            ),
            "cell_area": (("y", "x"), [[1.0]]),
        },
        coords={
            "timestamp": pd.date_range("2020-01-01", periods=2, freq="1D"),
            "latitude": (("y", "x"), [[10.0]]),
            "longitude": (("y", "x"), [[20.0]]),
        },
    )
    data["latitude_bounds"] = (("y", "bounds"), [[9.875, 10.125]])
    data["longitude_bounds"] = (("x", "bounds"), [[19.875, 20.125]])
    data = data.assign_coords(
        source_y_index=("y", [40]),
        source_x_index=("x", [80]),
        source_y_start=("y", [40]),
        source_y_stop=("y", [41]),
        source_x_start=("x", [80]),
        source_x_stop=("x", [81]),
        grid_y_index=("y", [40]),
        grid_x_index=("x", [80]),
    )
    data = add_aggregate_statistics(data, "sea_surface_temperature")
    path = block_path(scheme, "r3_c0", "web-test")
    path.parent.mkdir(parents=True)
    data.to_netcdf(path)
    record = {
        "repository": "noaancei",
        "dataset": "emsst",
        "variable": "sea_surface_temperature",
        "additional_parameters": {},
        "bucket_id": "r3_c0",
        "block_id": "web-test",
        "coarseness_factor": 1,
        "temporal_resolution": "1D",
        "native_temporal_resolution": "1D",
        "native_spatial_resolution": 0.25,
        "product_type": "native",
        "time_start": "2020-01-01T00:00:00",
        "time_end": "2020-01-02T00:00:00",
        "block_summary": {
            "lon_min": 20.0,
            "lon_max": 20.0,
            "lat_min": 10.0,
            "lat_max": 10.0,
        },
    }
    scheme.metadata.write_text(json.dumps(record) + "\n")
    return replace(
        get_settings(),
        container_schemes={"capacity_1": scheme},
        coarseness_to_spatial_level={1: scheme},
        _query_results=tmp_path / "results",
    )


def _query():
    return {
        "repository": "noaancei",
        "dataset": "emsst",
        "variable": "sea_surface_temperature",
        "region": {"west": 0, "east": 40, "south": 0, "north": 20},
        "time_start": "2020-01-01",
        "time_end": "2020-01-02",
        "coarseness_factor": 1,
        "time_unit": "Day",
        "function": "timeseries",
        "aggregation_method": "mean",
        "additional_parameters": {},
    }


def test_catalog_and_timeseries_query_boundary(tmp_path):
    settings = _settings(tmp_path)
    app.dependency_overrides[api_settings] = lambda: settings
    try:
        client = TestClient(app)
        catalog = client.get("/api/catalog")
        assert catalog.status_code == 200
        assert catalog.json()["coarseness_factors"] == [1]
        combined = next(
            dataset
            for repository in catalog.json()["repositories"]
            for dataset in repository["datasets"]
            if dataset["name"] == "combined"
        )
        assert combined["display_name"] == settings.name_docs["polaris"][
            "combined"
        ]["display_name"]

        availability = client.get("/api/availability")
        assert availability.status_code == 200
        assert availability.json()["rows"] == [
            {
                "repository": "noaancei",
                "dataset": "emsst",
                "variable": "sea_surface_temperature",
                "additional_parameters": {},
                "region": {
                    "west": 20.0,
                    "east": 20.0,
                    "south": 10.0,
                    "north": 10.0,
                },
                "time_start": "2020-01-01T00:00:00",
                "time_end": "2020-01-02T00:00:00",
                "spatial_resolutions": [0.25],
                "temporal_resolutions": ["1D"],
            }
        ]

        response = client.post("/api/queries", json=_query())
        assert response.status_code == 200
        body = response.json()
        assert body["function"] == "timeseries"
        assert len(body["groups"]) == 1
        group = body["groups"][0]
        assert group["grid"]["resolution"] == [0.25]
        assert group["coarseness_factor"] == 1
        assert group["data"] == {
            "kind": "timeseries",
            "timestamps": ["2020-01-01T00:00:00", "2020-01-02T00:00:00"],
            "values": [280.0, 282.0],
        }

        download = client.get(group["download_url"])
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/x-netcdf"
        assert download.content
    finally:
        app.dependency_overrides.clear()


def test_invalid_query_is_reported_as_validation_error(tmp_path):
    settings = _settings(tmp_path)
    app.dependency_overrides[api_settings] = lambda: settings
    try:
        response = TestClient(app).post(
            "/api/queries",
            json={**_query(), "region": {"west": 40, "east": 0, "south": 0, "north": 20}},
        )
        assert response.status_code == 422
        assert "west < east" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_heatmap_query_returns_plot_ready_coordinates(tmp_path):
    settings = _settings(tmp_path)
    app.dependency_overrides[api_settings] = lambda: settings
    try:
        response = TestClient(app).post(
            "/api/queries",
            json={**_query(), "function": "heatmap"},
        )
        assert response.status_code == 200
        data = response.json()["groups"][0]["data"]
        assert data == {
            "kind": "heatmap",
            "cell_ids": [response.json()["groups"][0]["group_id"] + ":c1:40:80"],
            "latitudes": [10.0],
            "longitudes": [20.0],
            "source_y_indices": [40],
            "source_x_indices": [80],
            "source_y_starts": [40],
            "source_y_stops": [41],
            "source_x_starts": [80],
            "source_x_stops": [81],
            "grid_y_indices": [40],
            "grid_x_indices": [80],
            "corner_latitudes": [[9.875, 9.875, 10.125, 10.125]],
            "corner_longitudes": [[19.875, 20.125, 20.125, 19.875]],
            "values": [281.0],
        }
    finally:
        app.dependency_overrides.clear()
