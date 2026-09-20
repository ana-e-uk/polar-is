"""Session-local query definitions used by the Polar-is CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DataObject:
    name: str
    repository: str
    dataset: str
    variable: str
    time_start: str
    time_end: str
    time_unit: str
    south: float
    north: float
    west: float
    east: float
    coarseness_factor: int
    aggregation_method: str
    additional_parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("-", "_").isalnum():
            raise ValueError("Data object name must contain letters, numbers, _ or -")
        if self.south >= self.north:
            raise ValueError("south must be less than north")
        if self.west >= self.east:
            raise ValueError("west must be less than east")
        if self.coarseness_factor < 1:
            raise ValueError("coarseness factor must be a positive integer")

    def query(
        self,
        function: str,
        *,
        predicate: str | None = None,
        filter_value: float | None = None,
    ) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "dataset": self.dataset,
            "variable": self.variable,
            "region": {
                "west": self.west,
                "east": self.east,
                "south": self.south,
                "north": self.north,
            },
            "time_start": self.time_start,
            "time_end": self.time_end,
            "time_unit": self.time_unit,
            "coarseness_factor": self.coarseness_factor,
            "function": function.lower().replace("_", "-"),
            "aggregation_method": self.aggregation_method,
            "additional_parameters": dict(self.additional_parameters),
            "predicate": predicate,
            "filter_value": filter_value,
        }

    def __str__(self) -> str:
        return (
            f"{self.name}: {self.repository}/{self.dataset} {self.variable}, "
            f"{self.time_start} to {self.time_end}, "
            f"region=({self.west}, {self.south}, {self.east}, {self.north})"
        )
