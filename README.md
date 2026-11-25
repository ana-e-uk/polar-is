# POLAR-IS

Sections:
- [Overview](#overview) lists services and general commands of POLAR-IS.
- [Dev Docs](#dev-docs) provides a more detailed description of the POLAR-IS internals.

## Overview

1. Access POLAR-IS through a [Web interface](#access-data-through-web-interface) and [Command-line interface](#access-data-through-command-line-interface)
    * Full documentation on APIs: [api.md](/api/documentation/api.md)
2. POLAR-IS services:
    * [Query data](#query-data)
    * [Available data](#available-data)
3. Create a POLAR-IS copy [locally](#create-a-local-copy)

### **Access data through web interface**

POLAR-IS web interface can be accessed at https://iharpv.cs.umn.edu. 

Note the interface may not be available during server maintenance.

### **Access data through command-line-interface**

1. Download and install command-line interface

```bash
git clone https://github.com/ana-e-uk/polar-is.git
cd polar-is
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

2. Initialize command-line interface once `polar-is` is installed. This will connect to the default server.

```bash
.venv/bin/polar-is \
  --output ./polar-is-results
```

  * `--output` sets the initial download directory.

  * Run `help` or `?` to see a list of commands, or find more information in the command-line interface [documentation](/api/documentation/command-line.md).

### **Query data**

POLAR-IS supports the following functions:

| Function | Result |
|---|---|
| `get-data` | Selected time × space data |
| `timeseries` | Spatially collapses the region; one value per timestamp |
| `heatmap` | Temporally collapses the interval; one value per cell |
| `find-time` | Full timeseries plus a Boolean `matches` array |
| `find-area` | Full heatmap plus a Boolean `matches` array |

A query can be made using the CLI and the web interface. Accepted jobs are added to a query.

### **Available data**
* *NOAA Climate Data Record (CDR) of Sea Surface Temperature - WHOI, Version 2*

  Clayson, Carol Anne; Brown, Jeremiah; and NOAA CDR Program (2016). NOAA Climate Data Record (CDR) of Sea Surface Temperature - WHOI, Version 2. Jan.1,2018 to Jan.31,2018. NOAA National Centers for Environmental Information. https://doi.org/10.7289/V5FB510W [2026].

* *Ensemble Median Global sea surface temperature dataset from 1988-01-01 to 2019-02-28 (NCEI Accession 0187983)*

  Tomita, Hiroyuki; Hihara, Tsutomu (2019). Ensemble Median Global sea surface temperature dataset from 1988-01-01 to 2019-02-28 (NCEI Accession 0187983). Jan.1,2018 to Jan.31,2018. NOAA National Centers for Environmental Information. Dataset. https://www.ncei.noaa.gov/archive/accession/0187983. Accessed 2026.

* *The NOAA Merged Land Ocean Global Surface Temperature Analysis (NOAAGlobalTemp, formerly known as MLOST)*

  Huang, B., X. Yin, M. J. Menne, R. Vose, NOAA Global Surface Temperature Dataset (NOAAGlobalTemp), Version 6.1.0. Jan.1,2018 to Jan.31,2018. NOAA National Centers for Environmental Information. https://doi.org/10.25921/vvaa-wq11.

* *C3S Arctic Regional Reanalysis (CARRA)*

  Schyberg H., Yang X., Køltzow M.A.Ø., Amstrup B., Bakketun Å., Bazile E., Bojarova J., Box J. E., Dahlgren P., Hagelin S., Homleid M., Horányi A., Høyer J., Johansson Å., Killie M.A., Körnich H., Le Moigne P., Lindskog M., Manninen T., Nielsen Englyst P., Nielsen K.P., Olsson E., Palmason B., Peralta Aros C., Randriamampianina R., Samuelsson P., Stappers R., Støylen E., Thorsteinsson S., Valkonen T., Wang Z.Q., (2020): Arctic regional reanalysis on single levels from 1991 to present. Copernicus Climate Change Service (C3S) Climate Data Store (CDS). DOI: 10.24381/cds.713858f6 (Accessed on 07-02-2026)
       
* *ERA5 hourly data on single levels from 1940 to present**

  Hersbach, H., Bell, B., Berrisford, P., Biavati, G., Horányi, A., Muñoz Sabater, J., Nicolas, J., Peubey, C., Radu, R., Rozum, I., Schepers, D., Simmons, A., Soci, C., Dee, D., Thépaut, J-N. (2023): ERA5 hourly data on single levels from 1940 to present. Copernicus Climate Change Service (C3S) Climate Data Store (CDS), DOI: 10.24381/cds.adbb2d47 (Accessed on 07-02-2026)

### **Create a local copy**

A local copy of POLAR-IS can manage local data in the same way it is managed in the remote POLAR-IS. This copy can be tailored for the local data. Follow [Dev Docs](#dev-docs) to initialize POLAR-IS.

# Dev Docs

1. Overview
    * [Pipeline visualization and definitions](#overview)
    * [Start system](#start-system-a-b) initialize POLAR-IS from no data.
    * [Start interfaces](#start-interfaces-c) start the frontend APIs to access data in POLAR-IS.
2. Details
    * [Requirements](#project-requirements)
    * [A. Get data](#a-get-data) how POLAR-IS gets source data.
    * [B. Process data into POLAR-IS](#b-process-data-into-polar-is) how POLAR-IS ingests data (indexing, aggregating, etc.).
    * [C. Answer queries](#c-answer-queries) how queries are handled.
3. Edit POLAR-IS
    * [Web development](#local-web-development)
    * [Code updates](#update-code-or-dependencies)

## Overview

**General pipeline**

A. Get data:

```text
User data interest/data request
            |
            ▼
    get_remote_data.py
            |
            ▼
Remote or manually obtained NetCDF files
            |
            ▼
    downloaded_data.jsonl
```

B. Process data into POLAR-IS:

```text
Files described in download_data.jsonl
            |
            ▼
    standardize.py
            |
            ▼
Standardized source datasets, combined dataset
            |
            ▼
    aggregate_data.py
            |
            └─ Grid catalog
            └─ Bucket lookup
            └─ Product datasets
            |
            ▼
Product partitions + metadata.jsonl
```

C. Answer queries:

```text
Data managed by POLAR-IS
            |
            ▼
Query planner/executor
            |
            ▼
APIs
    └─ FastAPI/React
    └─ CLI
```

**Definitions:**
| Term | Meaning in this codebase |
|---|---|
| Repository | A source dataset provider, such as Copernicus CDS or NOAA NCEI. |
| Dataset | A named dataset collection from a repository, such as ERA5 or CARRA. |
| Dataset variant | A dataset plus its instance-specific additional parameters, such as CARRA `height=15m, region=east`. |
| Variable | A canonical scientific field, such as `sea_surface_temperature`. |
| Grid | The complete reusable spatial geometry defining a 2D representation of Earth: latitude/longitude, projection, bounds, shape, and cell areas. |
| Bucket | A coarse geographic lookup region used to narrow a spatial search. It is not where data are physically stored. Current configuration: 60 lon x 30 lat global grid; six columns by six rows, i.e. 36 buckets. |
| Container | The generic name used by the grid-partition helper. Currently used to construct the bucket grid. |
| Source | Data at the dataset’s native time cadence and native spatial resolution. |
| Coarseness factor | Spatial grouping relative to the native grid. Factor 2 groups approximately 2×2 native cells. |
| Product | One precomputed temporal/spatial form of a dataset, such as Day/factor-1 or Month/factor-2. Stores sufficiant statistics rather than only the final mean. Also referred to as 'derived product'. |
| Partition/block | A physical NetCDF file containing one time range of a product or source. |
| Partition/block index | `metadata.jsonl`, which tells the planner where partitions are and what they cover. |
| Data object | A CLI session object containing a query’s repository, dataset, variable, region, time interval, resolution, and aggregation. |
| Result group | One result for one matching dataset variant/grid. A broad query may return several groups. |
| Combined | A separately materialized weighted mean dataset at a specified temporal-spatial resolution. Currently: daily, 0.5 deg. regular lat/lon grid. |

### **Start system** (pipeline parts A, B)

**1. Provide Data:** *Source* data can be added manually to the[downloaded_data](storage/data/tmp/downloaded/) directory or requested and downloaded through the process described in [storage.md](storage/documentation/storage.md). 

**2. Ingest Data:** [downloaded_data.jsonl](storage/data/tmp/downloaded/downloaded_data.jsonl) should describe the data to be processed into POLAR-IS. `standardize.py` and `aggregate_data.py` will read this file and ingest all data described in it.

```bash
.venv/bin/python -m storage.ingest_data.get_remote_data
.venv/bin/python -m storage.ingest_data.standardize
.venv/bin/python -m storage.ingest_data.aggregate_data
```

If there are multiple datasets, `combine_data.py` creates a joint dataset combining the values of one variable from multiple datasets.

```bash
.venv/bin/python -m storage.ingest_data.combine_data
```

### **Start interfaces** (pipeline part C)

To start the APIs:

Install project
```bash
cd <path to project directory>/polar-is

python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test,plot]'
```

Build the frontend as a single-worker FastAPI service application
```bash
cd api/interface/frontend
npm install
npm run build
cd ../../..
```

Start a local or online instance of the interface. 

LOCAL:
```bash
POLARIS_ACCESS_MODE=anonymous \
    .venv/bin/uvicorn api.interface.app:app \
    --host 127.0.0.1 \
    --port 8001 \
    --workers 1
```
or for local development:
```bash
POLARIS_ACCESS_MODE=anonymous .venv/bin/uvicorn api.interface.app:app --reload
```

ONLINE (official web interface):
```bash
nohup .venv/bin/uvicorn api.interface.app:app \
  --host 0.0.0.0 \
  --port 8001 \
  --workers 1 \
  > ../output.txt 2>&1 &
```

To use the command-line interface (CLI):

*University server:* 
```bash 
.venv/bin/polar-is --output ./polar-is-results
```
*Local server:*
```bash 
.venv/bin/polar-is --server http://127.0.0.1:8000 --output ./polar-is-results
```

**+++** Behind the scenes **+++**

* `pyproject.toml` contains dependencies, including `polar-is` entry point
* [`config.yaml`](config.yaml) specifies database parameters
* FastAPI mounts `frontend/dist` at `/` when that directory exists (see app.py)
* The queue and job registry are in memory, so the server must use one Uvicorn process. 
* Results expire after ten minutes by default.

## Details

### Project requirements

Software

- Python >=3.12
- Node.js 20.19+ or 22.12+
- npm
- Git
- Python dependencies from `pyproject.toml`
- ESMPy/ESMF for xESMF regridding
- Reverse proxy (e.g. Apache)
- Service manager like systemd
- TLS certificate for HTTPS

Hardware

- Storage: raw data + generated hierarchy + temporary workspace

Credentials

- Copernicus/CDS credentials for remote downloads
- Credentials stored outside Git

### Pipeline part A. Get data
**Get source data**

Source files can be retireved by POLAR-IS when data interests are provided by a user. POLAR-IS uses this information to generate and send requests to remote repositories and download data. The process is driven by `get_remote_data.py` [<- WORK IN PROGRESS]. 

Alternatively, source files can also be added and described in [downloaded_data.jsonl](storage/data/tmp/downloaded/downloaded_data.jsonl) manually.

**+++** Behind the scenes **+++**

* *Extensibility:* It is possible to add access to a new repository to POLAR-IS, a new dataset from a supported repository, or a variable from a supported dataset by following the steps in the *HOW_TO_* [docs](storage/documentation/).


### Pipeline part B. Process data into POLAR-IS
**Ingest source data**

The *source* files are standardized, aggregated to generate a set of *products* at predetermined resolutions, and both the *sources* and *products* are indexed.

The index generated consists of *catalogs*, *buckets*, and *partition files*.

For means, the executor combines the weighted sum and weight sum instead of averaging averages. The minimum and maximum use the precomputed sufficient statistics.


**+++** Behind the scenes **+++**

* `standardize.py`
* `aggregate_data.py`
* `combine_data.py`


### Partline part C. Answer queries
**Query processing**

A query can be made using a CLI and a web interface. Both interfaces use the job service in `query_service.py` and `job_service.py`. 

A query can be limited by estimated query duration, spatial cells, matching storage blocks, result values, number of result groups, and file output size (see [api.md](api/documentation/api.md) for more info).

POLAR-IS query path is split into planning and execution:

The planning stage validates the query submitted by the user via the interface or CLI. Then, it uses the dataset, partition, and bucket information to determine how to answer the query: what data is available, where and how it is stored, etc..

The execution stage follows the query plan and returns the result to the user. Each result records information that was queried including the dataset, parameters, `grid_id`, etc..

**+++** Behind the scenes **+++**

* `datasets.jsonl` contains dataset identities and parameters.
* `metadata.jsonl` has product partitions.
* `<grid_id>.jsonl` stores the bucket lookups for spatial candidates.

## Edit POLAR-IS

### **Local web development**

Terminal 1:

```bash
cd <path to project directory>/polar-is
POLARIS_ACCESS_MODE=anonymous \
    .venv/bin/uvicorn api.interface.app:app --reload
```

Terminal 2:

```bash
cd <path to project directory>/polar-is/api/interface/frontend
npm run dev
```

Vite proxies `/api` to FastAPI.

### **Update code or dependencies**

1. Stop the service
2. Pull the intended branch/commit
3. Re-run the editable Python installation if dependencies changed
4. Run `npm ci && npm run build` if frontend code or dependencies changed
5. Restart the web interface
6. Run tests and a small query

| File                  | Elements                                                                                                                                       |
|-----------------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| `config.py`           | * Dataset names <br>* Variable mappings<br>* Interface-facing titles for variables, repos, etc.<br>* Reducers<br>* Limits<br>* Combined policy |
| `aggregate_data.py`   | * Temporal/spatial product policy                                                                                                              |
| `api/interface/`      | * `frontend/src` - Web controls and layout<br>* `app.py` - API routes and authentication                                                       |
| `api/command_line`    | * CLI commands                                                                                                                                 |
| `storage/query_data/` | * `query_data.py` - query planning<br>* `executor.py` - query calculation                                                                      |
| `polaris/`            | * Frontend services used by both APIs (log queries, execute queries (jobs). etc.)                                                              |
| `storage/`            | * Defines objects and code pertaining to the index and data<br>* Where data is stored

## Code base

**Main directories**

```text
├── api/
│   ├── command_line/
│   └── interface/
│       └── frontend/
├── benchmarks/
├── polaris/
│   ├── services/
│   └── visualization/
├── storage/
│   ├── data/
│   │   ├── bucket_lookup/
│   │   ├── catalogs/
│   │   │   └── grids/
│   │   ├── products/
│   │   ├── regridding/
│   │   │   └── weights/
│   │   └── tmp/
│   │       ├── downloaded/
│   │       ├── query_results/
│   │       └── standardized/
│   ├── ingest_data/
│   │   └── get_remote_data/
│   └── query_data/
└── tests/
```