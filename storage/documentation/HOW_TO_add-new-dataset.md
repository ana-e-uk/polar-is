# Adding New Dataset
How to add an additional dataset of a currently supported repository to polar-is/storage.

For repository **remoterepo**, add a new dataset **new_dataset**:

1. Add the dataset to the **`DATASET EXECUTORS`** imports and dictionary at the top of `../repo__remoterepo/executor.py`

```python
"""
#####################################################################################
DATASET EXECUTORS
"""
#
# Imports
#
from datasets import era5_single_level
from datasets import carra_height
from datasets import new_dataset

#
# Dictionary
#
DATASETS = {
    "ERA5_SINGLE": era5_single_level,
    "CARRA_HEIGHT": carra_height,
    "NEW_DATASET": new_dataset,
}
"""
#####################################################################################
DATASET EXECUTORS
"""
```

2. Create a new file with the dataset name in the `datasets` folder, e.g.:

```bash
vim ~/polar-is/storage/polaris-initialize/repo__remoterepo/datasets/new_dataset.py
```

3. `new_dataset.py` file will have a function that builds the dataset-specific part of the request. This function must be called **`build_request`** in order for the executor script to be able to call this function for all dataset scripts.

```python
def build_request(query: DataRow) -> dict[str, Any]:
        request = {...
        }

        return request
```

4. Add a new key-value pair to the **"remoterepo"** dictionary in the `grids` dictionary in `config.yaml`. For this example, we would add `"new_dataset": "regular-lat-lon"`, assuming the grid/projection that **new_dataset** is a regular latitude-longitude grid.

```python
grids: {
  "copernicusclimatedatastore": {
    "era5_single_level": "regular-lat-lon",
    "carra_heigth": "lambert-conformal",
  },
    ...
  }
  "remoterepo": {
    "new_dataset": "regular-lat-lon",       # <-- ADDED new_dataset GRID NAME
  }
}
```

5. Test the new repository.