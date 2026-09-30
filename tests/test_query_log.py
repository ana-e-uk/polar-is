from datetime import datetime, timezone
import json

from api.command_line.client import PolarIsClient
from polaris.services.query_log import append_query_log


def test_query_log_appends_complete_json_lines(tmp_path):
    path = tmp_path / "logs" / "queries.jsonl"
    query = {"dataset": "era5_single_level", "function": "timeseries"}

    append_query_log(
        path,
        job_id="job-one",
        client="interface",
        owner="anonymous",
        outputs=("plot-json", "netcdf"),
        query=query,
        submitted_at=datetime(2026, 9, 23, 12, 30, tzinfo=timezone.utc),
    )
    append_query_log(
        path,
        job_id="job-two",
        client="unexpected-client",
        owner="alice",
        outputs=("netcdf",),
        query={"dataset": "carra_height", "function": "get-data"},
        submitted_at=datetime(2026, 9, 23, 12, 31, tzinfo=timezone.utc),
    )

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records == [
        {
            "job_id": "job-one",
            "submitted_at": "2026-09-23T12:30:00Z",
            "client": "interface",
            "owner": "anonymous",
            "outputs": ["plot-json", "netcdf"],
            "query": query,
        },
        {
            "job_id": "job-two",
            "submitted_at": "2026-09-23T12:31:00Z",
            "client": "api",
            "owner": "alice",
            "outputs": ["netcdf"],
            "query": {"dataset": "carra_height", "function": "get-data"},
        },
    ]


def test_cli_identifies_its_queries_without_logging_credentials():
    client = PolarIsClient("https://example.test", "secret-token")

    headers = client._headers()

    assert headers["X-Polaris-Client"] == "cli"
    assert headers["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in headers["X-Polaris-Client"]
