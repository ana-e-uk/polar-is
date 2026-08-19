from pathlib import Path
from unittest.mock import Mock, patch

from storage.ingest_data.standardize import unique_output_path


def test_unique_output_path_retries_collision(tmp_path):
    (tmp_path / "collision.nc").touch()
    generated_ids = [Mock(hex="collision"), Mock(hex="available")]

    with patch(
        "storage.ingest_data.standardize.uuid4",
        side_effect=generated_ids,
    ):
        path = unique_output_path(
            tmp_path,
            unique_type="uuid",
            max_attempts=2,
        )

    assert path == tmp_path / "available.nc"


def test_unique_output_path_raises_after_max_attempts(tmp_path):
    (tmp_path / "collision.nc").touch()

    with patch(
        "storage.ingest_data.standardize.uuid4",
        return_value=Mock(hex="collision"),
    ):
        try:
            unique_output_path(
                tmp_path,
                unique_type="uuid",
                max_attempts=10,
            )
        except ValueError as error:
            assert "after 10 attempts" in str(error)
        else:
            raise AssertionError("Repeated filename collisions did not fail")


def test_random_output_path_uses_requested_directory(tmp_path):
    relative_directory = Path(tmp_path.name) / "blocks"
    absolute_directory = tmp_path.parent / relative_directory

    path = unique_output_path(
        absolute_directory,
        unique_type="random",
    )

    assert path.parent == absolute_directory
    assert len(path.stem.split("_")) == 2
