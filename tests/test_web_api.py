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

        response = client.post("/api/queries", json=_query())
        assert response.status_code == 200
        body = response.json()
        assert body["function"] == "timeseries"
        assert len(body["groups"]) == 1
        group = body["groups"][0]
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
        assert response.json()["groups"][0]["data"] == {
            "kind": "heatmap",
            "latitudes": [10.0],
            "longitudes": [20.0],
            "values": [281.0],
        }
    finally:
        app.dependency_overrides.clear()
