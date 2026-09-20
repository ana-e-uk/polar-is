"""Small plotting model shared by static renderers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from storage.query_data.executor import GroupResult
from polaris.services.result_serializer import grid_mapping, serialize_plot_data


@dataclass(frozen=True)
class PlotModel:
    group_id: str
    function: str
    source_label: str
    variable: str
    units: str | None
    grid_mapping: dict[str, Any] | None
    data: dict[str, Any]


def build_plot_model(group: GroupResult, function: str) -> PlotModel:
    """Build the rendering input for one executor result group."""
    details = ", ".join(
        f"{name}={value}"
        for name, value in sorted(group.source.additional_parameters.items())
    )
    source = f"{group.source.repository} / {group.source.dataset}"
    if details:
        source = f"{source} ({details})"
    return PlotModel(
        group_id=group.group_id,
        function=function,
        source_label=source,
        variable=group.source.variable,
        units=group.units,
        grid_mapping=grid_mapping(group.data, group.source.variable),
        data=serialize_plot_data(group, function),
    )
