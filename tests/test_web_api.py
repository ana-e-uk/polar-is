from dataclasses import replace
import json
import time

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from api.interface.app import (
    _grid_mapping,
    api_settings,
    app,
    validate_access_configuration,
)
from polaris.config import ContainerScheme, get_settings
from polaris.services.job_service import job_service
from storage.ingest_data.aggregate_data import add_aggregate_statistics
from storage.ingest_data.make_data_blocks import block_path


@pytest.fixture(autouse=True)
def _explicit_anonymous_access(monkeypatch):
    monkeypatch.setenv("POLARIS_ACCESS_MODE", "anonymous")


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
    job_service.clear()
    try:
        client = TestClient(app)
        catalog = client.get("/api/catalog")
        assert catalog.status_code == 200
        assert catalog.json()["coarseness_factors"] == [1]
        assert catalog.json()["frontend_titles"] == settings.frontend_titles
        noaa = next(
            repository
            for repository in catalog.json()["repositories"]
            if repository["name"] == "noaancei"
        )
        assert noaa["display_name"] == (
            "NOAA National Centers for Environmental Information"
        )
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

        response = client.post(
            "/api/v1/jobs",
            json={"query": _query(), "outputs": ["plot-json", "netcdf"]},
        )
        assert response.status_code == 202
        body = _wait_for_job(client, response.json()["job_id"])["result"]
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
        job_service.clear()


def test_invalid_query_is_reported_as_validation_error(tmp_path):
    settings = _settings(tmp_path)
    app.dependency_overrides[api_settings] = lambda: settings
    try:
        response = TestClient(app).post(
            "/api/v1/jobs",
            json={
                "query": {
                    **_query(),
                    "region": {"west": 40, "east": 0, "south": 0, "north": 20},
                },
                "outputs": ["plot-json"],
            },
        )
        assert response.status_code == 422
        assert "west < east" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_heatmap_query_returns_plot_ready_coordinates(tmp_path):
    settings = _settings(tmp_path)
    app.dependency_overrides[api_settings] = lambda: settings
    job_service.clear()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/jobs",
            json={
                "query": {**_query(), "function": "heatmap"},
                "outputs": ["plot-json", "png"],
            },
        )
        assert response.status_code == 202
        result = _wait_for_job(client, response.json()["job_id"])["result"]
        data = result["groups"][0]["data"]
        assert data == {
            "kind": "heatmap",
            "cell_ids": [result["groups"][0]["group_id"] + ":c1:40:80"],
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
        completed = _wait_for_job(client, response.json()["job_id"])
        png = client.get(completed["groups"][0]["png_url"])
        assert png.status_code == 200
        assert png.content.startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        app.dependency_overrides.clear()
        job_service.clear()


def test_grid_mapping_serializes_cf_lambert_parameters():
    data = xr.Dataset(
        {"value": ("cell", [1.0], {"grid_mapping": "crs"})},
        coords={
            "crs": xr.DataArray(
                np.int8(0),
                attrs={
                    "grid_mapping_name": "lambert_conformal_conic",
                    "standard_parallel": np.asarray([72.0, 72.0]),
                    "longitude_of_central_meridian": -36.0,
                    "latitude_of_projection_origin": 72.0,
                    "crs_wkt": "intentionally omitted from the browser payload",
                },
            )
        },
    )

    assert _grid_mapping(data, "value") == {
        "grid_mapping_name": "lambert_conformal_conic",
        "standard_parallel": [72.0, 72.0],
        "longitude_of_central_meridian": -36.0,
        "latitude_of_projection_origin": 72.0,
    }


def _wait_for_job(client, job_id):
    for _ in range(1000):
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in {"completed", "failed"}:
            return body
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_async_job_returns_plot_json_and_netcdf(tmp_path):
    settings = _settings(tmp_path)
    app.dependency_overrides[api_settings] = lambda: settings
    job_service.clear()
    try:
        client = TestClient(app)
        created = client.post(
            "/api/v1/jobs",
            json={"query": _query(), "outputs": ["plot-json", "png", "netcdf"]},
        )
        assert created.status_code == 202
        completed = _wait_for_job(client, created.json()["job_id"])
        assert completed["status"] == "completed"
        assert completed["result"]["groups"][0]["data"]["values"] == [280.0, 282.0]
        group = completed["groups"][0]
        assert client.get(group["plot_json_url"]).status_code == 200
        png = client.get(group["png_url"])
        assert png.status_code == 200
        assert png.headers["content-type"] == "image/png"
        assert png.content.startswith(b"\x89PNG\r\n\x1a\n")
        data = client.get(group["data_url"])
        assert data.status_code == 200
        assert data.headers["content-type"] == "application/x-netcdf"
    finally:
        app.dependency_overrides.clear()
        job_service.clear()


def test_job_access_is_scoped_to_bearer_token(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    app.dependency_overrides[api_settings] = lambda: settings
    monkeypatch.setenv("POLARIS_ACCESS_MODE", "token")
    monkeypatch.setenv("POLARIS_API_TOKENS", '{"first": "alice", "second": "bob"}')
    job_service.clear()
    try:
        client = TestClient(app)
        created = client.post(
            "/api/v1/jobs",
            headers={"Authorization": "Bearer first"},
            json={"query": _query(), "outputs": ["netcdf"]},
        )
        assert created.status_code == 202
        job_id = created.json()["job_id"]
        forbidden = client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"Authorization": "Bearer second"},
        )
        assert forbidden.status_code == 403
        missing = client.get(f"/api/v1/jobs/{job_id}")
        assert missing.status_code == 401
        completed = None
        for _ in range(100):
            response = client.get(
                f"/api/v1/jobs/{job_id}",
                headers={"Authorization": "Bearer first"},
            )
            completed = response.json()
            if completed["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert completed is not None and completed["status"] == "completed"
    finally:
        app.dependency_overrides.clear()
        job_service.clear()


def test_anonymous_mode_needs_no_token_and_reports_public_status(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path)
    app.dependency_overrides[api_settings] = lambda: settings
    monkeypatch.setenv("POLARIS_ACCESS_MODE", "anonymous")
    monkeypatch.setenv("POLARIS_API_TOKENS", '{"unused": "alice"}')
    job_service.clear()
    previous_owner_limit = job_service.max_queued_per_owner
    job_service.max_queued_per_owner = -1
    try:
        client = TestClient(app)
        status_response = client.get("/api/v1/status")
        assert status_response.status_code == 200
        assert status_response.json() == {
            "access_mode": "anonymous",
            "running_jobs": 0,
            "queued_jobs": 0,
            "queue_capacity": job_service.max_active_jobs,
        }

        created = client.post(
            "/api/v1/jobs",
            json={"query": _query(), "outputs": ["netcdf"]},
        )
        assert created.status_code == 202
        assert _wait_for_job(client, created.json()["job_id"])["status"] == "completed"
    finally:
        job_service.max_queued_per_owner = previous_owner_limit
        app.dependency_overrides.clear()
        job_service.clear()


def test_token_mode_configuration_requires_tokens(monkeypatch):
    monkeypatch.setenv("POLARIS_ACCESS_MODE", "token")
    monkeypatch.delenv("POLARIS_API_TOKENS", raising=False)

    with pytest.raises(RuntimeError, match="requires POLARIS_API_TOKENS"):
        validate_access_configuration()


def test_access_mode_must_be_explicit(monkeypatch):
    monkeypatch.delenv("POLARIS_ACCESS_MODE")

    with pytest.raises(RuntimeError, match="POLARIS_ACCESS_MODE must be set"):
        validate_access_configuration()


def test_preflight_rejects_oversized_query_before_enqueue(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path)
    app.dependency_overrides[api_settings] = lambda: settings
    monkeypatch.setenv("POLARIS_ACCESS_MODE", "anonymous")
    monkeypatch.setenv("POLARIS_MAX_SPATIAL_CELLS", "10")
    job_service.clear()
    try:
        response = TestClient(app).post(
            "/api/v1/jobs",
            json={"query": _query(), "outputs": ["netcdf"]},
        )
        assert response.status_code == 422
        assert "Estimated spatial cells" in response.json()["detail"]
        assert job_service.status()["running_jobs"] == 0
        assert job_service.status()["queued_jobs"] == 0
    finally:
        app.dependency_overrides.clear()
        job_service.clear()


def test_full_global_queue_returns_friendly_response(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    app.dependency_overrides[api_settings] = lambda: settings
    monkeypatch.setenv("POLARIS_ACCESS_MODE", "anonymous")
    previous_capacity = job_service.max_active_jobs
    job_service.max_active_jobs = 0
    try:
        response = TestClient(app).post(
            "/api/v1/jobs",
            json={"query": _query(), "outputs": ["netcdf"]},
        )
        assert response.status_code == 429
        assert response.json()["detail"] == "Polar-is is busy; try again shortly"
        assert response.headers["retry-after"] == "5"
    finally:
        job_service.max_active_jobs = previous_capacity
        app.dependency_overrides.clear()
        job_service.clear()
