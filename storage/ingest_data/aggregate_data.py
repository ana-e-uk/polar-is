from dask.distributed import LocalCluster
import dask
import xarray as xr
import pandas as pd
import os

"""
EXCERPT FROM PREVIOUS VERSION OF POLARIS: I think the structure might be good, except the 
data is from multiple datasets now so it needs to be more general, I want to store the different
aggregations in one file (maybe), and it is in the old format/etc. I also don't think it needs 
dask anymore because I am partitioning the files before aggregating them so they should be smaller
"""

class Aggregate:

    STATS = ["mean", "min", "max"]

    TEMPORAL_FREQS = {
        "day": "D",
        "month": "ME",
        "year": "YE",
    }

    SPATIAL_SCALES = {
        "05": 2,
        "1": 4,
    }

    CHUNKS = "auto"

    def __init__(self, file_name: str, dataset: str, variable: str, time_range: str, additional:str):
        self.file_name = file_name
        self.dataset = dataset
        self.variable = variable
        self.time_range = time_range
        self.additional = additional

        self.short_name = long_short_name_dict[variable]
        self.encoding = {self.short_name: encodings[dataset]}
        self.base_name = f"{variable}_{time_range}_{additional}"

        self.records = []

        self.dims = DATASET_GRID_DIMS[self.dataset]

    def _log_record(self, outfile, temporal_res, spatial_res, aggregation):

        # assuming time_range is just one year
        start_str = f"{self.time_range}-01-01 00:00"
        end_str = f"{self.time_range}-12-31 23:00"
        record = {
            "variable": self.variable,
            "start_datetime":start_str,
            "end_datetime":end_str,
            "max_lat": -1,
            "min_lat": -1,
            "min_lon": -1,
            "max_lon": -1,
            "temporal_resolution": temporal_res,
            "spatial_resolution": spatial_res,
            "aggregation": aggregation,
            "file_path": outfile,
            "additional": self.additional,
        }
        pd.DataFrame([record]).to_csv(f"/data/{self.dataset}/{self.base_name}_agg_metadata_interim.csv", mode="a", header=not os.path.exists(f"/data/{self.dataset}/{self.base_name}_agg_metadata_interim.csv"), index=False)
        self.records.append(record)

    def _apply_stat(self, obj, stat):
        return getattr(obj, stat)()

    def _spatial_aggregate(self, ds, stat):
        """Return spatially aggregated datasets."""

        lat_dim = self.dims["y"]
        lon_dim = self.dims["x"]

        outputs = {}
        for label, coarse in self.SPATIAL_SCALES.items():
            coarsened = ds.coarsen(
                {lat_dim: coarse, lon_dim: coarse},
                boundary="trim",
            )
            outputs[label] = self._apply_stat(coarsened, stat)

        return outputs

    def time_driver(self):

        print(f"Temporal aggregation: {self.file_name}")

        ds = xr.open_dataset(
            f"/data/{self.dataset}/{self.file_name}.nc",
            chunks=self.CHUNKS,
        )

        writes = []

        time_dim = self.dims["time"]
        for label, freq in self.TEMPORAL_FREQS.items():
            resampler = ds.resample(time_dim=freq)
            for stat in self.STATS:
                result = self._apply_stat(resampler, stat)
                outfile = f"/data/{self.dataset}/{self.base_name}_025{label}_{stat}.nc"
                self._log_record(
                                outfile,
                                temporal_res=label,
                                spatial_res="0.25",
                                aggregation=stat,
                                )
                delayed = result.to_netcdf(outfile,encoding=self.encoding,compute=False,)
                writes.append(delayed)

        dask.compute(*writes)

    def space_driver(self):

        print(f"Spatial aggregation: {self.file_name}")

        writes = []

        for time_label in self.TEMPORAL_FREQS.keys():
            for stat in self.STATS:
                infile = f"/data/{self.dataset}/{self.base_name}_025{time_label}_{stat}.nc"      # ASSUMING file names are in format defined in time_driver()
                ds = xr.open_dataset(
                    infile,
                    chunks=self.CHUNKS,
                )
                spatial_outputs = self._spatial_aggregate(ds, stat)
                for space_label, result in spatial_outputs.items():
                    outfile = f"/data/{self.dataset}/{self.base_name}_{space_label}{time_label}_{stat}.nc"
                    self._log_record(
                                    outfile,
                                    temporal_res=time_label,
                                    spatial_res=space_label,
                                    aggregation=stat,
                                    )
                    delayed = result.to_netcdf(outfile,encoding=self.encoding,compute=False,)
                    writes.append(delayed)

        dask.compute(*writes)

    def finest_space_driver(self):

        print(f"Hourly spatial aggregation: {self.file_name}")

        ds = xr.open_dataset(
            f"/data/{self.dataset}/{self.file_name}.nc",
            chunks=self.CHUNKS,
        )

        writes = []

        for stat in self.STATS:
            spatial_outputs = self._spatial_aggregate(ds, stat)
            for space_label, result in spatial_outputs.items():
                outfile = f"/data/{self.dataset}/{self.base_name}_{space_label}hour_{stat}.nc"
                self._log_record(
                                outfile,
                                temporal_res="hour",
                                spatial_res=space_label,
                                aggregation=stat,
                                )
                delayed = result.to_netcdf(outfile,encoding=self.encoding,compute=False,)
                writes.append(delayed)

        dask.compute(*writes)

    def execute(self):

        self.time_driver()
        self.space_driver()
        self.finest_space_driver()

        # Save metadata
        df = pd.DataFrame(self.records)
        df.to_csv(f"/data/{self.dataset}/{self.base_name}_agg_metadata.csv", index=False)