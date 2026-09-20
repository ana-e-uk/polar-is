# Polar-is web interface

The first interface slice uses FastAPI for HTTP requests and a Vite-built
React/TypeScript application for the browser. FastAPI serves the production
frontend from `frontend/dist` so the application has one origin.

## Install

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test,plot]'
cd api/interface/frontend
npm install
npm run build
```

## Run the built application

Build the browser application once before starting the public server:

```bash
cd api/interface/frontend
npm install
npm run build
cd ../../..
```

For anonymous conference access on the university host, start FastAPI from the
repository root:

```bash
export POLARIS_ACCESS_MODE=anonymous
unset POLARIS_API_TOKENS
export POLARIS_JOB_WORKERS=2
export POLARIS_MAX_ACTIVE_JOBS=10
export POLARIS_MAX_QUEUED_PER_USER=100
export POLARIS_RESULT_TTL_SECONDS=600
export POLARIS_MAX_QUERY_DAYS=31
export POLARIS_MAX_SPATIAL_CELLS=25000
export POLARIS_MAX_MATCHING_BLOCKS=100
export POLARIS_MAX_RESULT_VALUES=500000
export POLARIS_MAX_RESULT_GROUPS=5
export POLARIS_MAX_OUTPUT_BYTES=52428800

nohup .venv/bin/uvicorn api.interface.app:app \
  --host 0.0.0.0 \
  --port 8001 \
  --workers 1 \
  > ../output.txt 2>&1 &
```

`POLARIS_JOB_WORKERS=2` runs two queries concurrently inside the shared job
queue. Keep Uvicorn at `--workers 1`: each Uvicorn process would otherwise have
an independent in-memory queue and job registry. If the university HTTPS proxy
runs on this same computer, prefer `--host 127.0.0.1`; otherwise use the address
and firewall policy supplied by the administrator. The per-user setting is
ignored in anonymous mode; lower it to the desired individual limit before
switching to token mode.

The HTTPS reverse proxy can serve both clients from one origin:

```text
Browser: https://iharpv.cs.umn.edu/
CLI:     https://iharpv.cs.umn.edu/api/v1/jobs
```

The university reverse proxy should apply IP-based rate limiting and forward
the public HTTPS origin to port 8001. Polar-is itself enforces the shared job
capacity and returns HTTP 429 with `Retry-After` when it is busy.

For local development, run:

```bash
POLARIS_ACCESS_MODE=anonymous .venv/bin/uvicorn api.interface.app:app --reload
```

Then open <http://127.0.0.1:8000>. The interactive API documentation is at
<http://127.0.0.1:8000/docs>.

The prototype asynchronous queue lives inside this process. Run one Uvicorn
worker; multiple independent workers would have separate in-memory queues.

## Prototype job API and access modes

Both the web interface and CLI submit jobs to `POST /api/v1/jobs`, then poll
`GET /api/v1/jobs/{job_id}`. Query metadata is kept in memory and generated
artifacts expire after ten minutes by default.

Set the access mode explicitly. Conference mode accepts browser and CLI jobs
without credentials:

```bash
export POLARIS_ACCESS_MODE=anonymous
```

Polar-is refuses to start if `POLARIS_ACCESS_MODE` is missing or unsupported,
so omitting a token configuration cannot accidentally select public access.

In anonymous mode, the global active-job limit is enforced and the per-owner
limit is skipped because all participants share an anonymous identity. After
the conference, token mode can be enabled with a token-to-owner mapping:

```bash
export POLARIS_ACCESS_MODE=token
export POLARIS_API_TOKENS='{"replace-with-a-random-token":"researcher-name"}'
```

The server refuses to start in token mode when the token mapping is absent,
empty, or invalid. This is an auditable prototype boundary, not a self-service
identity system.

Optional tuning variables are:

```text
POLARIS_JOB_WORKERS             default 2
POLARIS_MAX_QUEUED_PER_USER     default 3
POLARIS_MAX_ACTIVE_JOBS         default 20
POLARIS_RESULT_TTL_SECONDS      default 600
POLARIS_MAX_QUERY_DAYS          default 31
POLARIS_MAX_SPATIAL_CELLS       default 25000
POLARIS_MAX_MATCHING_BLOCKS     default 100
POLARIS_MAX_RESULT_VALUES       default 500000
POLARIS_MAX_RESULT_GROUPS       default 5
POLARIS_MAX_OUTPUT_BYTES        default 52428800
```

Before a job enters the queue, Polar-is reads the storage index and estimates
its spatial cells, time intervals, matching blocks, result values, and source
groups. Requests over a configured limit are rejected without opening the
matching NetCDF blocks. Repository and dataset filters remain optional, so one
bounded request may still return several matching datasets.

## Expired-output cleanup

The server removes known expired jobs during normal API use and removes stale
output from previous runs at startup. For cleanup independent of API traffic,
run this command periodically (for example, every five minutes from cron):

```bash
cd /path/to/polar-is
.venv/bin/python -m polaris.services.cleanup
```

Example crontab entry (replace both paths with absolute paths on the server):

```cron
*/5 * * * * cd /path/to/polar-is && /path/to/polar-is/.venv/bin/python -m polaris.services.cleanup >> /path/to/polar-is-cleanup.log 2>&1
```

The command skips jobs with a fresh `.active` marker. A marker older than one
day is treated as residue from a crashed process. Preview cleanup without
deleting anything with:

```bash
.venv/bin/python -m polaris.services.cleanup --dry-run
```

`GET /api/v1/status` is public and reports the access mode, running jobs,
queued jobs, and shared queue capacity.

## Develop the frontend

Run FastAPI on port 8000, then start Vite in a second terminal:

```bash
cd api/interface/frontend
npm run dev
```

Vite proxies `/api` requests to FastAPI. Rebuild the frontend before testing
the single-origin production form.

## Test

```bash
.venv/bin/python -m pytest
cd api/interface/frontend
npm run build
```

## Topology-aware query results

Area results use topology stored during ingestion. Each flattened query cell
contains stable source and requested-grid indices, its geographic center, four
geographic corners, and projected coordinates when the source grid is
projected. CARRA also carries a CF Lambert conformal grid mapping. Consequently,
the frontend draws the cell polygons returned by the API; it does not estimate
cell size from latitude/longitude.

`find-time` and `find-area` return the complete aggregated result plus a
Boolean `matches` array. The frontend plots the complete result and overlays
the matching time points or cell outlines.

Blocks created before this topology was added must be rebuilt from the source
data. Follow the ingestion commands in `storage/documentation/DOCS_ingest.md`.
The standardization command consumes the files listed in
`downloaded_data.jsonl`, so retain copies if those files are needed elsewhere.
