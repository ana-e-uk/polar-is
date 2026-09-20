import os

from dataclasses import replace

from polaris.config import get_settings
from polaris.services.cleanup import cleanup_stale_outputs


def test_cleanup_removes_expired_jobs_but_preserves_active_and_unknown(tmp_path):
    settings = replace(get_settings(), _query_results=tmp_path / "results")
    jobs = settings._query_results / "jobs"
    expired = jobs / ("a" * 32)
    active = jobs / ("b" * 32)
    unknown = jobs / "notes"
    expired.mkdir(parents=True)
    active.mkdir()
    unknown.mkdir()
    marker = active / ".active"
    marker.touch()
    os.utime(expired, (0, 0))
    os.utime(marker, (990, 990))
    os.utime(active, (990, 990))

    removed = cleanup_stale_outputs(
        settings,
        max_age_seconds=100,
        active_grace_seconds=500,
        now=1_000,
    )

    assert removed == (expired,)
    assert not expired.exists()
    assert active.exists()
    assert unknown.exists()
