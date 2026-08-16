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
    _data: Path
    _downloaded: Path
    _standardized: Path
    # files
    interests_: Path
    requests_: Path
    downloaded_data_: Path
    standardized_data_: Path
    metadata_: Path
    buckets_: Path
    # dictionaries
    name_docs: dict

@lru_cache
def get_settings() -> Settings:
    with CONFIG_FILE.open() as file:
        raw = yaml.safe_load(file)

    return Settings(
        _initialize=PROJECT_ROOT / raw["initialize_dir"],
        _data=PROJECT_ROOT / raw["data_dir"],
        _downloaded=PROJECT_ROOT / raw["downloaded_data_dir"],
        _standardized=PROJECT_ROOT / raw["standardized_data_dir"],
        interests_=PROJECT_ROOT / raw["interests"],
        requests_=PROJECT_ROOT / raw["requests"],
        downloaded_data_=PROJECT_ROOT / raw["downloaded_data"],
        standardized_data_=PROJECT_ROOT / raw["standardized_data"],
        metadata_=PROJECT_ROOT / raw["metadata"],
        buckets_=PROJECT_ROOT / raw["buckets"],
        name_docs=raw.get("name_docs", {}),
    )