from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config.yaml"


@dataclass(frozen=True)
class ContainerScheme:
    name: str
    factor: int
    data_dir: Path
    metadata: Path
    definitions: Path


@dataclass(frozen=True)
class Settings:
    # directories
    _initialize: Path
    _downloaded: Path
    _standardized: Path
    # files
    interests_: Path
    requests_: Path
    downloaded_data_: Path
    standardized_data_: Path
    # spatial container hierarchy
    container_grid: dict
    container_schemes: dict[str, ContainerScheme]
    coarseness_to_spatial_level: dict[int, ContainerScheme]
    temporal_aggregation_resolutions: tuple[str, ...]
    supported_query_functions: tuple[str, ...]
    function_aggregation_methods: tuple[str, ...]
    # dictionaries
    name_docs: dict
    aggregation_methods: dict

@lru_cache
def get_settings() -> Settings:
    with CONFIG_FILE.open() as file:
        raw = yaml.safe_load(file)

    schemes = {
        name: ContainerScheme(
            name=name,
            factor=int(values["factor"]),
            data_dir=PROJECT_ROOT / values["data_dir"],
            metadata=PROJECT_ROOT / values["metadata"],
            definitions=PROJECT_ROOT / values["definitions"],
        )
        for name, values in raw["container_schemes"].items()
    }
    coarseness_to_spatial_level = {
        int(coarseness): schemes[spatial_level]
        for coarseness, spatial_level in raw[
            "coarseness_to_spatial_level"
        ].items()
    }

    return Settings(
        _initialize=PROJECT_ROOT / raw["initialize_dir"],
        _downloaded=PROJECT_ROOT / raw["downloaded_data_dir"],
        _standardized=PROJECT_ROOT / raw["standardized_data_dir"],
        interests_=PROJECT_ROOT / raw["interests"],
        requests_=PROJECT_ROOT / raw["requests"],
        downloaded_data_=PROJECT_ROOT / raw["downloaded_data"],
        standardized_data_=PROJECT_ROOT / raw["standardized_data"],
        container_grid=raw["container_grid"],
        container_schemes=schemes,
        coarseness_to_spatial_level=coarseness_to_spatial_level,
        temporal_aggregation_resolutions=tuple(
            raw["temporal_aggregation_resolutions"]
        ),
        supported_query_functions=tuple(raw["supported_query_functions"]),
        function_aggregation_methods=tuple(
            raw["function_aggregation_methods"]
        ),
        name_docs=raw.get("name_docs", {}),
        aggregation_methods=raw["aggregation_methods"],
    )
