from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config.yaml"


@dataclass(frozen=True)
class Settings:
    # directories
    _initialize: Path
    _downloaded: Path
    _standardized: Path
    _query_results: Path
    # files
    interests_: Path
    requests_: Path
    downloaded_data_: Path
    standardized_data_: Path
    catalogs_dir: Path
    datasets_catalog: Path
    grids_catalog: Path
    grids_dir: Path
    bucket_lookup_dir: Path
    products_dir: Path
    product_index: Path
    combined_dataset: dict
    # shared geographic lookup grid
    container_grid: dict
    supported_coarseness_factors: tuple[int, ...]
    supported_query_functions: tuple[str, ...]
    function_aggregation_methods: tuple[str, ...]
    # dictionaries
    name_docs: dict
    frontend_titles: dict
    aggregation_methods: dict

@lru_cache
def get_settings() -> Settings:
    with CONFIG_FILE.open() as file:
        raw = yaml.safe_load(file)

    return Settings(
        _initialize=PROJECT_ROOT / raw["initialize_dir"],
        _downloaded=PROJECT_ROOT / raw["downloaded_data_dir"],
        _standardized=PROJECT_ROOT / raw["standardized_data_dir"],
        _query_results=PROJECT_ROOT / raw["query_results_dir"],
        interests_=PROJECT_ROOT / raw["interests"],
        requests_=PROJECT_ROOT / raw["requests"],
        downloaded_data_=PROJECT_ROOT / raw["downloaded_data"],
        standardized_data_=PROJECT_ROOT / raw["standardized_data"],
        catalogs_dir=PROJECT_ROOT / raw["catalogs_dir"],
        datasets_catalog=PROJECT_ROOT / raw["datasets_catalog"],
        grids_catalog=PROJECT_ROOT / raw["grids_catalog"],
        grids_dir=PROJECT_ROOT / raw["grids_dir"],
        bucket_lookup_dir=PROJECT_ROOT / raw["bucket_lookup_dir"],
        products_dir=PROJECT_ROOT / raw["products_dir"],
        product_index=PROJECT_ROOT / raw["product_index"],
        combined_dataset={
            **raw.get("combined_dataset", {}),
            "cache_dir": PROJECT_ROOT
            / raw.get("combined_dataset", {}).get(
                "cache_dir", "storage/data/regridding"
            ),
        },
        container_grid=raw["container_grid"],
        supported_coarseness_factors=tuple(
            int(value) for value in raw["supported_coarseness_factors"]
        ),
        supported_query_functions=tuple(raw["supported_query_functions"]),
        function_aggregation_methods=tuple(
            raw["function_aggregation_methods"]
        ),
        name_docs=raw.get("name_docs", {}),
        frontend_titles=raw.get("frontend_titles", {}),
        aggregation_methods=raw["aggregation_methods"],
    )
