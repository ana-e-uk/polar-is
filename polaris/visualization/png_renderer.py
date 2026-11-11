"""Render Polar-is query groups to static PNG files."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

import numpy as np

from polaris.visualization.plot_model import PlotModel


class PngRendererUnavailable(RuntimeError):
    """Raised when optional plotting dependencies are not installed."""


def _matplotlib():
    try:
        cache_root = Path(tempfile.gettempdir()) / "polar-is-plot-cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
        os.environ.setdefault("XDG_CACHE_HOME", str(cache_root))
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.collections import PolyCollection
        import cartopy.crs as ccrs
    except ImportError as error:
        raise PngRendererUnavailable(
            "PNG output requires the optional plotting dependencies. "
            "Install Polar-is with: pip install -e '.[plot]'"
        ) from error
    return plt, PolyCollection, ccrs


def _projection(model: PlotModel, ccrs):
    mapping = model.grid_mapping or {}
    if mapping.get("grid_mapping_name") == "lambert_conformal_conic":
        parallels = mapping.get("standard_parallel", (30, 60))
        if not isinstance(parallels, (list, tuple)):
            parallels = (parallels, parallels)
        return ccrs.LambertConformal(
            central_longitude=mapping.get("longitude_of_central_meridian", 0),
            central_latitude=mapping.get("latitude_of_projection_origin", 0),
            standard_parallels=tuple(parallels[:2]),
        )
    return ccrs.PlateCarree()


def render_png(model: PlotModel, output_path: Path) -> Path:
    """Render one plot model and return the created file path."""
    if model.function not in {"timeseries", "find-time", "heatmap", "find-area"}:
        raise ValueError(f"PNG output is not supported for {model.function!r}")

    plt, PolyCollection, ccrs = _matplotlib()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    label = model.variable if model.units is None else f"{model.variable} ({model.units})"
    data = model.data

    if model.function in {"timeseries", "find-time"}:
        figure, axes = plt.subplots(figsize=(9, 4.5), constrained_layout=True)
        timestamps = np.asarray(data["timestamps"], dtype="datetime64[s]")
        values = np.asarray([
            np.nan if value is None else value for value in data["values"]
        ], dtype=float)
        axes.plot(timestamps, values, marker=".", linewidth=1.8, label=model.variable)
        if model.function == "find-time" and "matches" in data:
            matches = np.asarray(data["matches"], dtype=bool)
            axes.scatter(
                timestamps[matches], values[matches], color="crimson", zorder=3,
                label="Matches filter",
            )
            if data.get("filter_value") is not None:
                axes.axhline(
                    data["filter_value"], color="crimson", linestyle="--",
                    alpha=0.7, label=f"Filter value = {data['filter_value']}",
                )
        axes.set(xlabel="Time", ylabel=label, title=f"{model.function}: {model.source_label}")
        axes.grid(alpha=0.25)
        axes.legend()
        figure.autofmt_xdate()
    else:
        figure, axes = plt.subplots(
            figsize=(8, 6), constrained_layout=True,
            subplot_kw={"projection": _projection(model, ccrs)},
        )
        values = np.asarray(data["values"], dtype=float)
        longitudes = np.asarray(data["longitudes"], dtype=float)
        latitudes = np.asarray(data["latitudes"], dtype=float)
        collection = axes.scatter(
            longitudes.ravel(), latitudes.ravel(), c=values.ravel(),
            cmap="viridis", marker="s", transform=ccrs.PlateCarree(),
        )
        colorbar = figure.colorbar(collection, ax=axes)
        colorbar.set_label(label)
        if model.function == "find-area" and "matches" in data:
            matches = np.asarray(data["matches"], dtype=bool)
            axes.scatter(
                longitudes[matches], latitudes[matches], facecolors="none",
                edgecolors="crimson", marker="s", linewidths=1.2,
                transform=ccrs.PlateCarree(),
            )
        axes.set(
            xlabel="Longitude", ylabel="Latitude",
            title=f"{model.function}: {model.source_label}",
        )
        axes.gridlines(draw_labels=True, alpha=0.2)

    temporary = output_path.with_name(output_path.name + ".partial")
    try:
        figure.savefig(temporary, format="png", dpi=150)
        temporary.replace(output_path)
    finally:
        plt.close(figure)
        temporary.unlink(missing_ok=True)
    return output_path
