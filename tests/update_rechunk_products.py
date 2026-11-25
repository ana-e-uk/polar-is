"""Atomically rechunk existing product partitions for regional reads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import xarray as xr

from polaris.config import Settings, get_settings
from storage.ingest_data.product_partitions import _chunk_encoding


def _indexed_product_paths(settings: Settings) -> tuple[Path, ...]:
    if not settings.product_index.is_file():
        return ()
    data_root = settings.product_index.parent.resolve()
    paths = []
    for line in settings.product_index.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        relative_path = json.loads(line)["relative_path"]
        path = (data_root / relative_path).resolve()
        if not path.is_relative_to(data_root):
            raise ValueError(f"Product path leaves storage root: {relative_path}")
        if path not in paths:
            paths.append(path)
    return tuple(paths)


def rechunk_product_file(path: Path, target_chunk_bytes: int) -> None:
    """Rewrite one file beside itself, then replace it only after validation."""
    temporary = path.with_name(f".{path.name}.rechunking")
    try:
        with xr.open_dataset(path, chunks={}) as source:
            expected_sizes = dict(source.sizes)
            expected_variables = set(source.variables)
            source.to_netcdf(
                temporary,
                encoding=_chunk_encoding(source, target_chunk_bytes),
            )
        with xr.open_dataset(temporary) as rewritten:
            if dict(rewritten.sizes) != expected_sizes:
                raise ValueError(f"Rechunk changed dimensions in {path}")
            if set(rewritten.variables) != expected_variables:
                raise ValueError(f"Rechunk changed variables in {path}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def rechunk_products(
    settings: Settings | None = None,
    *,
    target_chunk_bytes: int = 4 * 1024 * 1024,
) -> tuple[Path, ...]:
    """Rechunk every indexed product, preserving paths and catalog records."""
    settings = settings or get_settings()
    paths = _indexed_product_paths(settings)
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Indexed product does not exist: {path}")
        rechunk_product_file(path, target_chunk_bytes)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-mib",
        type=int,
        default=4,
        help="maximum uncompressed target chunk size in MiB (default: 4)",
    )
    arguments = parser.parse_args()
    paths = rechunk_products(target_chunk_bytes=arguments.target_mib * 1024 * 1024)
    print(f"Rechunked {len(paths)} indexed product files.")


if __name__ == "__main__":
    main()
