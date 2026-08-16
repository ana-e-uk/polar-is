from storage.initialize.get_remote_data.get_remote_data import DataRow
from storage.initialize.get_remote_data.repo__copernicusclimatedatastore.executor import requested_years, requested_months
from typing import Any

def build_request(query: DataRow) -> dict[str, Any]:
    additional_params = query.additional_params or {}

    request = {
        "domain": additional_params.get("domain"),
        "variable": query.variable,
        "height_level": additional_params.get("height_level"),
        "product_type": additional_params.get("product_type"),
        "time": [f"{i:02d}" for i in range(24)],
        "year": requested_years(query),
        "month": requested_months(query),
        "day": [f"{day:02d}" for day in range(1, 32)], 
        "data_format": "unarchived"
    }

    if additional_params.get("leadtime_hour"):
        request["leadtime_hour"] = additional_params.get("leadtime_hour")

    return request