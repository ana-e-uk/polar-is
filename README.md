# PolarIS: A Polar Data Infrastructure for Interactive and Scalable Science


PolarIS is a system built to be the software layer that manages data access,
storage, and usage for polar scientists. Below is information about how 
researchers can use the current PolarIS supported by the Data Management Lab
at the University of Minnesota for, how to initialize your own PolarIS, and
how it works.

Data currently supported by this version of PolarIS is:

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

---

## Using PolarIS

Two APIs are provided for scientists and researchers to access and explore
the data managed by PolarIS.

**Web Interface**

The web interface provided by PolarIS can be accessed at:

https://iharpv.cs.umn.edu

See `api/documentation/DOCS_api.md` for a description of 
available features.

**Command-line Interface**

Checkout `api/documentation/DOCS_command-line.md` for a detailed guide on 
initializing comand-line interface as a user and as an administrator. This
document also contains a list of available commands and error definitions.


* *Download and install command-line interface:*

The current version installs from the project repository and
requires Python 3.12 or newer:

```bash
git clone https://github.com/ana-e-uk/polar-is.git
cd polar-is
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

* *Initialize command-line interface* 

Once `polar-is` is installed, you can connect to the default 
server. Use `--output` to choose the initial download directory:

```bash
.venv/bin/polar-is \
  --output ./polar-is-results
```

Run `help` or `?` to see a list of commands, or find more information
in **DOCS_command-line.md**.

---

## Creating a Local Copy of PolarIS

A copy of PolarIS can be initialized locally. This copy will act the same as the remote PolarIS once it is set up with the remote repository access keys and other initial parameters. This local PolarIS will manage data downloads from remote repositories, data processing and storage. It provides fast and interactive query processing, and will monitor your storage to keep the most relevant data stored locally. 

* To start PolarIS from scratch, read `storage/documentation/DOCS_initialize.md`. To edit the initial geographical spatial partitioning, follow: `storage/documentation/HOW_TO_change-containers.md`.

* To add data to PolarIS, follow `storage/documentation/DOCS_ingest.md`.

* See the next section for the basic commands to start up the server for PolarIS. More detailed instructions are found in `api/interface/README.md`.


* *Starting PolarIS Server:*

**First time:** Install and initialize virtual environment.

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test,plot]'
```

* *Build the browser:*

Once the project has been installed, you can build the application. Remember to also build if any changes are made to the code.

```bash
cd api/interface/frontend
npm install
npm run build
```

* *Start FastAPI*

From the repository root:

```bash
nohup .venv/bin/uvicorn api.interface.app:app \
  --host 0.0.0.0 \
  --port 8001 \
  --workers 1 \
  > ../output.txt 2>&1 &
```

OR start a local instance at <http://127.0.0.1:8000>:

```bash
POLARIS_ACCESS_MODE=anonymous .venv/bin/uvicorn api.interface.app:app --reload
```

See various limits and modes you can set in additional documentation.

---

## Extending PolarIS

PolarIS is equipt to request data from multiple remote repositories and datasets. To add a new repository that is not supported, follow: `storage/documentation/HOW_TO_add-new-repo.md`. To support a new dataset stored within a currently supported repository, follow: `storage/documentation/HOW_TO_add-new-dataset.md`. `api/interface/README.md` has the commands to use when developing the frontend.

---


## Other Documentation 

* `storage/documentation/DOCS_manage.md` describes how PolarIS manages data in storage.

* `storage/documentation/DOCS_query.md` describes how queries are handled.

