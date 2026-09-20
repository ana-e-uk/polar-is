"""Interactive command-line client for a remote Polar-is service."""

from __future__ import annotations

import argparse
import cmd
from getpass import getpass
import os
from pathlib import Path
import shlex
from typing import Any

from api.command_line.client import PolarIsClient, PolarIsClientError
from api.command_line.data_object import DataObject


DATA_OBJECT_USAGE = (
    "data_object NAME REPOSITORY DATASET VARIABLE START END TIME_UNIT "
    "SOUTH NORTH WEST EAST COARSENESS AGGREGATION [KEY=VALUE ...]"
)
DEFAULT_SERVER_URL = "https://iharpv.cs.umn.edu"


def _parameters(values: list[str]) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Additional parameter must use KEY=VALUE: {value!r}")
        name, parameter = value.split("=", 1)
        if not name or not parameter:
            raise ValueError(f"Additional parameter must use KEY=VALUE: {value!r}")
        parameters[name] = parameter
    return parameters


class PolarIsCLI(cmd.Cmd):
    intro = "Polar-is remote CLI. Type help or ? to list commands."
    prompt = "Polar-is $ "

    def __init__(
        self,
        client: PolarIsClient,
        output_directory: Path | str = Path.cwd(),
    ) -> None:
        super().__init__()
        self.client = client
        self.output_directory = Path(output_directory).expanduser().resolve()
        self.data_objects: dict[str, DataObject] = {}

    def do_data_object(self, arg: str) -> None:
        """Create or replace a session object. Type: help data_object"""
        try:
            parts = shlex.split(arg)
            if len(parts) < 13:
                raise ValueError(f"Usage: {DATA_OBJECT_USAGE}")
            obj = DataObject(
                name=parts[0],
                repository=parts[1],
                dataset=parts[2],
                variable=parts[3],
                time_start=parts[4],
                time_end=parts[5],
                time_unit=parts[6],
                south=float(parts[7]),
                north=float(parts[8]),
                west=float(parts[9]),
                east=float(parts[10]),
                coarseness_factor=int(parts[11]),
                aggregation_method=parts[12],
                additional_parameters=_parameters(parts[13:]),
            )
            self.data_objects[obj.name] = obj
            print(f"Saved {obj}")
        except (ValueError, IndexError) as error:
            print(f"Could not create data object: {error}")

    def help_data_object(self) -> None:
        print(DATA_OBJECT_USAGE)
        print("Coordinates are SOUTH NORTH WEST EAST. Quote values containing spaces.")
        print("Example:")
        print(
            "  data_object sst noaancei emsst sea_surface_temperature "
            "2020-01-01 2020-01-31 Day 0 20 0 40 1 mean"
        )

    def do_objects(self, arg: str) -> None:
        """List data objects stored in this CLI session."""
        if not self.data_objects:
            print("No data objects are stored in this session.")
            return
        for obj in self.data_objects.values():
            print(obj)

    def do_catalog(self, arg: str) -> None:
        """List repositories, datasets, and variables available from the server."""
        try:
            catalog = self.client.catalog()
            for repository in catalog["repositories"]:
                if not repository["datasets"]:
                    continue
                print(f"{repository['name']}:")
                for dataset in repository["datasets"]:
                    variables = ", ".join(dataset["variables"]) or "no variables"
                    print(f"  {dataset['name']}: {variables}")
            print("Coarseness factors:", ", ".join(
                str(value) for value in catalog["coarseness_factors"]
            ))
            print("Time units:", ", ".join(catalog["time_units"]))
        except PolarIsClientError as error:
            print(f"Could not load catalog: {error}")

    def do_status(self, arg: str) -> None:
        """Show server access mode and current queue utilization."""
        if arg.strip():
            print("Usage: status")
            return
        try:
            status = self.client.status()
            print(f"Access mode: {status['access_mode']}")
            print(
                "Jobs: "
                f"{status['running_jobs']} running, "
                f"{status['queued_jobs']} queued, "
                f"{status['queue_capacity']} active-job capacity"
            )
        except PolarIsClientError as error:
            print(f"Could not load server status: {error}")

    def do_show(self, arg: str) -> None:
        """Show one data object: show NAME"""
        parts = shlex.split(arg)
        if len(parts) != 1:
            print("Usage: show NAME")
            return
        name = parts[0]
        if name not in self.data_objects:
            print(f"Unknown data object: {name!r}")
            return
        print(self.data_objects[name])
        print(self.data_objects[name].query("get-data"))

    def do_output(self, arg: str) -> None:
        """Show or set the download directory: output [DIRECTORY]"""
        if not arg.strip():
            print(self.output_directory)
            return
        parts = shlex.split(arg)
        if len(parts) != 1:
            print("Usage: output [DIRECTORY]")
            return
        directory = Path(parts[0]).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.output_directory = directory
        print(f"Downloads will be saved in {directory}")

    def do_login(self, arg: str) -> None:
        """Enter an access token without placing it in shell history."""
        if arg.strip():
            print("Usage: login (the token is requested securely)")
            return
        self.client.token = getpass("Polar-is access token: ").strip() or None
        print("Access token loaded for this session.")

    def do_logout(self, arg: str) -> None:
        """Forget the current in-memory access token."""
        self.client.token = None
        print("Access token removed from this session.")

    def _object(self, name: str) -> DataObject:
        try:
            return self.data_objects[name]
        except KeyError as error:
            raise ValueError(f"Unknown data object: {name!r}") from error

    def _run_and_download(
        self,
        obj: DataObject,
        query: dict[str, Any],
        output_kind: str,
        extension: str,
    ) -> None:
        created = self.client.create_job(query, [output_kind])
        job_id = str(created["job_id"])
        print(f"Submitted job {job_id}")
        completed = self.client.wait_for_job(
            job_id,
            on_status=lambda state, ahead: print(
                f"  queued ({ahead} job{'s' if ahead != 1 else ''} ahead)"
                if state == "queued" and ahead is not None
                else f"  {state}"
            ),
        )
        groups = completed.get("groups", [])
        if not groups:
            print("The query completed but returned no matching result groups.")
            return
        url_field = "png_url" if output_kind == "png" else "data_url"
        for group in groups:
            group_id = str(group["group_id"])
            destination = self.output_directory / (
                f"{obj.name}-{query['function']}-{group_id[:8]}.{extension}"
            )
            path = self.client.download(group[url_field], destination)
            print(f"Saved {path}")

    def do_plot(self, arg: str) -> None:
        """Generate PNG plot(s): plot NAME FUNCTION [PREDICATE VALUE]"""
        try:
            parts = shlex.split(arg)
            if len(parts) < 2:
                raise ValueError("Usage: plot NAME FUNCTION [PREDICATE VALUE]")
            obj = self._object(parts[0])
            function = parts[1].lower().replace("_", "-")
            predicate = None
            filter_value = None
            if function in {"find-time", "find-area"}:
                if len(parts) != 4:
                    raise ValueError(
                        f"{function} requires a predicate and numeric filter value"
                    )
                predicate = parts[2]
                filter_value = float(parts[3])
            elif len(parts) != 2:
                raise ValueError("Usage: plot NAME FUNCTION [PREDICATE VALUE]")
            self._run_and_download(
                obj,
                obj.query(
                    function, predicate=predicate, filter_value=filter_value
                ),
                "png",
                "png",
            )
        except (ValueError, PolarIsClientError, FileExistsError) as error:
            print(f"Plot failed: {error}")

    def do_download(self, arg: str) -> None:
        """Download data as NetCDF file(s): download NAME"""
        try:
            parts = shlex.split(arg)
            if len(parts) != 1:
                raise ValueError("Usage: download NAME")
            obj = self._object(parts[0])
            self._run_and_download(
                obj, obj.query("get-data"), "netcdf", "nc"
            )
        except (ValueError, PolarIsClientError, FileExistsError) as error:
            print(f"Download failed: {error}")

    def do_quit(self, arg: str) -> bool:
        """Exit and discard session data objects."""
        print("Exiting Polar-is.")
        return True

    do_exit = do_quit

    def do_EOF(self, arg: str) -> bool:
        print()
        return self.do_quit(arg)


def main() -> None:
    parser = argparse.ArgumentParser(description="Remote client for Polar-is")
    parser.add_argument(
        "--server",
        default=os.getenv("POLARIS_API_URL", DEFAULT_SERVER_URL),
        help="Polar-is server URL (default: POLARIS_API_URL or university server)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.cwd(),
        help="directory for downloaded files",
    )
    args = parser.parse_args()
    client = PolarIsClient(args.server, os.getenv("POLARIS_API_TOKEN"))
    PolarIsCLI(client, args.output).cmdloop()


if __name__ == "__main__":
    main()
