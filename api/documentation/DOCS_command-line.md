# Polar-is command-line client

The Polar-is CLI is a small interactive client for a remote Polar-is server. It
keeps named data objects in memory, submits asynchronous query jobs, and
downloads static PNG plots or NetCDF data files. Data objects disappear when
the CLI exits locally.

The CLI does not need a local copy of the managed environmental data.

## Download and install

The current version installs from the project repository and
requires Python 3.12 or newer:

```bash
git clone https://github.com/ana-e-uk/polar-is.git
cd polar-is
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

This installs the `polar-is` command. A packaged release can use the same
entry point when the project is later published to a Python package index.

## Connect to a server

The CLI defaults to the server specified in [`DEFAULT_SERVER_URL`](https://github.com/ana-e-uk/polar-is/blob/aa296ea1b2b326df8032c3a2fb2000e095b23725/api/command_line/cli.py#L21) in file **cli.py**. You can also pass it explicitly:

```bash
.venv/bin/polar-is --server https://iharpv.cs.umn.edu
```

The website interface and CLI use the same server. The browser loads `/`, while the CLI
sends asynchronous jobs to `/api/v1/jobs`; a separate CLI server is not needed.

Use `--output` to choose the initial download directory:

```bash
.venv/bin/polar-is \
  --server https://iharpv.cs.umn.edu \
  --output ./polar-is-results
```

For local development, pass `--server http://127.0.0.1:8000`.
`POLARIS_API_URL` can also replace the default URL.

## Anonymous access

If the server administrator sets `POLARIS_ACCESS_MODE=anonymous`, anyone can
start the CLI and begin querying. No account, login command, token, or server 
argument is required:

```bash
.venv/bin/polar-is
```

Use `status` to check whether the server is anonymous and how busy its shared
queue is. When a submitted job is queued, the CLI reports how many running or
earlier queued jobs are ahead of it. If the shared queue is full, it reports
that Polar-is is busy and asks the user to try again shortly.

## Token access

If the administrator changes the server to `POLARIS_ACCESS_MODE=token`, users
must enter a `login` and paste an issued access token at the hidden prompt:

```text
Polar-is $ login
Polar-is access token:
Access token loaded for this session.
```

The prototype keeps this token in memory and forgets it when the CLI exits.
It is not written to disk. `logout` forgets it immediately.

For automated local testing, `POLARIS_API_TOKEN` can supply a token. Avoid
placing real tokens directly in shell commands or source-controlled files.

## Discover available data

Use `catalog` to list repository, dataset, variable, coarseness, and time-unit
names accepted by the connected server:

```text
Polar-is $ catalog
noaancei:
  emsst: sea_surface_temperature
Coarseness factors: 1, 2, 4
Time units: Hour, Day, Month, Year, Source
```

## Create a data object

The complete syntax is:

```text
data_object NAME REPOSITORY DATASET VARIABLE START END TIME_UNIT SOUTH NORTH WEST EAST COARSENESS AGGREGATION [KEY=VALUE ...]
```

Coordinates are ordered as `SOUTH NORTH WEST EAST`. For example:

```text
Polar-is $ data_object sst noaancei emsst sea_surface_temperature 2020-01-01 2020-01-31 Day 0 20 0 40 1 mean
```

The command above creates a session object named `sst`. It does not run a
query. Use `objects` to list session objects and `show sst` to inspect one.

Datasets with additional parameters accept `KEY=VALUE` arguments at the end:

```text
Polar-is $ data_object carra copernicusclimatedatastore carra_height sea_surface_temperature 2020-01-01 2020-01-31 Day 55 85 -80 20 2 mean height=15m region=east
```

## Download a plot

The supported plot functions are `timeseries`, `heatmap`, `find-time`, and
`find-area`:

```text
Polar-is $ plot sst timeseries
Polar-is $ plot sst heatmap
Polar-is $ plot sst find-time gt 281
Polar-is $ plot sst find-area le 275
```

The CLI submits a job, reports its state, and downloads one PNG for each
returned dataset result. Multiple files are expected when a query matches
multiple datasets or parameter combinations.

PNG generation requires the Polar-is server (administrator)—not the CLI computer 
(user)—to install the optional plotting dependencies.

## Download data

Use `download` to run the data object's `get-data` query and retrieve NetCDF:

```text
Polar-is $ download sst
```

One NetCDF file is downloaded per returned dataset.

## Output files

Use `output` to show or change the download directory:

```text
Polar-is $ output
/current/output/directory
Polar-is $ output ./results
Downloads will be saved in /absolute/path/to/results
```

Filenames contain the data-object name, query function, and a shortened group
identifier. The client refuses to overwrite an existing file. Move or rename
an earlier result before repeating the same download.

## Other commands

```text
catalog          List available data
status           Show access mode and queue utilization
objects          List session data objects
show NAME        Inspect one session data object
output [PATH]    Show or change the download directory
login            Enter a token at a hidden prompt
logout           Forget the current token
quit             Exit and discard session data objects
help             Show command help
```

## Limitations

- The server queue is in memory, so jobs may be lost when the server restarts.
- The CLI is interactive; non-interactive one-shot commands are not implemented.
- Anonymous mode uses IP-based rate limits supplied by the current HTTPS 
  reverse proxy, while Polar-is bounds query cost and the shared queue.
- Token mode is a configurable bearer-token prototype pending integration with
  a university-approved identity provider.
- Generated results expire on the server. Files already downloaded by the CLI
  are unaffected.

## Troubleshooting

`401 A valid Polar-is access token is required`
: The server is in token mode. Run `login` and enter a token issued by its
  administrator.

`429 Polar-is is busy; try again shortly`
: The queue is full. Wait briefly and submit the job again.

`422` response
: The server rejected a field or the query exceeded a configured limit. 
  Check `catalog`, coordinate order, time unit, and coarseness.

`Job failed: PNG output requires the optional plotting dependencies`
: The server administrator must install `.[plot]` and restart the server.

`Refusing to overwrite`
: Change the output directory or move the existing downloaded file.
