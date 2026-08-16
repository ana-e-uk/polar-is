from storage.initialize.get_remote_data.get_remote_data import DataRow
from storage.initialize.get_remote_data.repo__copernicusclimatedatastore.executor import requested_years, requested_months, request_area
from typing import Any

def build_request(query: DataRow) -> dict[str, Any]:
    additional_params = query.additional_params or {}

    return {
        "product_type": additional_params.get("product_type"),
        "variable": query.variable,
        "year": requested_years(query),
        "month": requested_months(query),
        "day": [f"{day:02d}" for day in range(1, 32)],
        "time": [f"{i:02d}" for i in range(24)],
        "data_format": "netcdf",
        "area": request_area(query),
        "download_format": "unarchived"
    }