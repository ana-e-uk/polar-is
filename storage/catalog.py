"""Small, JSON-serializable records for the storage catalogs and index.

The grid catalog describes canonical full grids.  Product coverage is described
separately by its global grid window, so cropped products from the same grid
retain the same ``grid_id``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import string
from typing import Any, Mapping, Self


CATALOG_SCHEMA_VERSION = 1


def stable_128_bit_id(value: Mapping[str, Any]) -> str:
    """Return a deterministic compact identifier for a JSON identity."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.blake2b(encoded, digest_size=16).hexdigest()


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_128_bit_id(name: str, value: str) -> None:
    _require_text(name, value)
    if len(value) != 32 or any(
        character not in string.hexdigits for character in value
    ):
        raise ValueError(f"{name} must be a 128-bit hexadecimal identifier")


def _require_relative_path(name: str, value: str) -> None:
    _require_text(name, value)
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{name} must be a relative path without '..'")


def _require_window(
    y_start: int,
    y_stop: int,
    x_start: int,
    x_stop: int,
) -> None:
    if min(y_start, x_start) < 0:
        raise ValueError("grid window starts must be non-negative")
    if y_stop <= y_start or x_stop <= x_start:
        raise ValueError("grid window stops must be greater than starts")


class JsonRecord:
    """Shared conversion helpers for the catalog dataclasses."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> Self:
        return cls(**dict(values))


@dataclass(frozen=True)
class GridCatalogRecord(JsonRecord):
    """Location and shape of one canonical, finest-resolution grid."""

    grid_id: str
    grid_type: str
    shape_y: int
    shape_x: int
    relative_path: str
    schema_version: int = CATALOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_128_bit_id("grid_id", self.grid_id)
        if self.grid_type not in {"rectilinear", "projected"}:
            raise ValueError("grid_type must be 'rectilinear' or 'projected'")
        if self.shape_y <= 0 or self.shape_x <= 0:
            raise ValueError("grid shapes must be positive")
        _require_relative_path("relative_path", self.relative_path)


@dataclass(frozen=True)
class DatasetCatalogRecord(JsonRecord):
    """Metadata shared by every product from one dataset variant.

    Scientifically meaningful singleton source coordinates belong in
    ``additional_parameters``.  Technical singleton coordinates are omitted.
    """

    dataset_variant_id: str
    repository: str
    dataset: str
    additional_parameters: dict[str, Any]
    variables: dict[str, dict[str, Any]]
    display_name: str | None = None
    schema_version: int = CATALOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text("dataset_variant_id", self.dataset_variant_id)
        _require_text("repository", self.repository)
        _require_text("dataset", self.dataset)
        if not isinstance(self.additional_parameters, dict):
            raise ValueError("additional_parameters must be a dictionary")
        if not isinstance(self.variables, dict) or not self.variables:
            raise ValueError("variables must be a non-empty dictionary")


@dataclass(frozen=True)
class ProductIndexRecord(JsonRecord):
    """One time partition of a dataset product in the shared index."""

    partition_id: str
    dataset_variant_id: str
    variable: str
    grid_id: str
    temporal_resolution: str
    coarseness_factor: int
    time_start: str
    time_end: str
    grid_y_start: int
    grid_y_stop: int
    grid_x_start: int
    grid_x_stop: int
    relative_path: str
    schema_version: int = CATALOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_128_bit_id("partition_id", self.partition_id)
        _require_128_bit_id("grid_id", self.grid_id)
        for name in (
            "dataset_variant_id",
            "variable",
            "temporal_resolution",
            "time_start",
            "time_end",
        ):
            _require_text(name, getattr(self, name))
        if self.coarseness_factor < 1:
            raise ValueError("coarseness_factor must be positive")
        if self.time_end < self.time_start:
            raise ValueError("time_end must not be before time_start")
        _require_window(
            self.grid_y_start,
            self.grid_y_stop,
            self.grid_x_start,
            self.grid_x_stop,
        )
        _require_relative_path("relative_path", self.relative_path)

    def resolved_path(self, storage_root: Path) -> Path:
        """Derive the physical path without storing an absolute path."""
        return storage_root / PurePosixPath(self.relative_path)


@dataclass(frozen=True)
class BucketWindowRecord(JsonRecord):
    """A bucket's rectangular lookup window on one canonical grid.

    More than one record may use the same ``grid_id`` and ``bucket_id`` when a
    longitude seam requires multiple windows.
    """

    grid_id: str
    bucket_id: str
    grid_y_start: int
    grid_y_stop: int
    grid_x_start: int
    grid_x_stop: int
    schema_version: int = CATALOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_128_bit_id("grid_id", self.grid_id)
        _require_text("bucket_id", self.bucket_id)
        _require_window(
            self.grid_y_start,
            self.grid_y_stop,
            self.grid_x_start,
            self.grid_x_stop,
        )
