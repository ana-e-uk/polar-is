# Adding New Repository
How to add additional repositories to polar-is/storage.

For repository **remote repo**:

1. Create a new file folder with name: **repo__remoterepo**. Name convention: add **repo__** to the start of the folder name, then have the minimum unique name of the repository in lowercase with no spaces inbetween.

```bash
mkdir ~/polar-is/storage/polaris-initialize/repository-hooks/repo__remoterepo
```

2. Within `repo__remoterepo` create:
        * `__init__.py`
        * `executor.py` with a **`run`** function that will call the correct dataset function that will initialize the remote repository request. 
        * `datasets` folder that will hold the different dataset scripts.

3. In the script `get_remote_data.py`, add the new remote repository executor to the imports and dictionary in the **`REMOTE REPOSITORY EXECUTORS`** following the format below:

```python
"""
#####################################################################################
REMOTE REPOSITORY EXECUTORS
"""
#
# Imports
#
from repo__copernicusclimatedatastore import executor as copernicusclimatedatastore_executor
from repo__nasaearthdata import executor as nasaearthdata_executor
from repo__remoterepo import executor as remoterepo_executor

#
# Dictionary
# 
EXECUTORS = {
        "Copernicus_climatedatastore": copernicusclimatedatastore_executor,
        "NASA_earthdata": nasaearthdata_executor,
        "Remote_repo": remoterepo_executor
}
"""
REMOTE REPOSITORY EXECUTORS
#####################################################################################
"""
```

4. `executor.py` structure: *Header*, *Imports*, *Dataset executors*, *Helper functions*, ***`run()`** function*:

```python
"""

REMOTE REPOSITORY: < remote repo name >

LINK: < link to remote repo >

DESCRIPTION: < general description of script and repository >

"""
from get_remote_data import DataRow
# other imports

"""
#####################################################################################
DATASET EXECUTORS
"""
#
# Imports
#

#
# Dictionary
#

"""
#####################################################################################
DATASET EXECUTORS
"""

# Helper functions


# run() function 
# IN:   dataset: str - name of dataset
#       query: dict - DataRow
#       temp_fn: str - temporary file name 
# OUT: None

```

5. Add a new key to the `grids` dictionary in `config.yaml` that has the same name as the second part of the repository file folder. In this case, it would be **"remoterepo"**. This key should be initialized with an empty dictionary that will be filled with dataset names and dataset grid names as key-value pairs. 

6. Test the new repository.