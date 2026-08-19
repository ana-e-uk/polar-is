"""Split standardized data into blocks.

Each cell in a dataset grid will be classified into a bucket
based on the bucket the cell center falls into. All the cells
corresponding to one bucket will be stored together in one
file. This group of cells is called a block. A dataset may
have multiple blocks. 
"""
import xarray as xr
from pathlib import Path
import numpy as np

from storage.manage.space_buckets import map_buckets, N_COLS
from storage.ingest_data.standardize import read_metadata, write_metadata, unique_output_path

from polaris.config import get_settings


def make_block_record(record, bucket: str, bounds: list, path: Path):
    """Generate a block record .
    
    Add block-specific region, coordinates, bucket_code and file_path
    """
    block_record = {
        **record,
        "bucket_code": bucket,
        "bounds": bounds,
        "file_path": path
    }
    return block_record

def bounding_rectangle(block: xr.Dataset) -> list:
    """Find a bounding rectangle of the data cells in a block.
    
    This can be used to further filter the blocks in a bucket
    during a query.
    """
    # TODO: make sure this works for 2D and 1D coordinates. May need to pass in dataset grid type
    min_lat = block["latitude"].min()
    max_lat = block["latitude"].max()
    min_lon = block["longitude"].min()
    max_lon = block["longitude"].max()

    return [min_lat, max_lat, min_lon, max_lon]

def calc_bucket_id(code):
    row = code // N_COLS
    col = code % N_COLS
    return f"r{row}_c{col}"

def make_data_blocks(records, out_dir, metadata_path):

    block_metadata = []

    # For each standardized file
    for record in records:

        file_path = record["file_path"]

        # Save block information
        # all blocks from a record should have the same repo,dataset,var,sp.res,t.res
        # NOTE: Assume the time interval and additional params are the same for all blocks for now
        base_record = {
            **record
        }
        base_record.pop("file_path")

        with xr.open_dataset(file_path) as data:

            # Get a mask assigning a bucket code to each data cell
            bucket_codes_mask = map_buckets(data)

            # Filter data cells by each bucket
            for bucket_code in np.unique(bucket_codes_mask):
                mask = bucket_codes_mask == bucket_code
                block = data.where(mask, drop=True)

                # Find MBR of block (could be bucket or subset of bucket)
                bounds = bounding_rectangle(block)

                # Assert bucket directory exists (should be storage/data/{bucket_id}
                bucket_id = calc_bucket_id(bucket_code)
                path = Path(out_dir, bucket_code)
                path.parent.mkdir(parents=True, exist_ok=True)

                # Save resulting data block
                output_path = unique_output_path(
                    directory= path,
                    unique_type="random",
                    )
                block.to_netcdf(output_path)

                # Make block-specific record
                block_record = make_block_record(
                    record=base_record,
                    bucket=bucket_code,
                    bounds=bounds,
                    path=output_path,
                    )
                
                block_metadata.append(block_record)

    write_metadata(metadata_path, block_metadata)

if __name__ == "__main__":

    settings = get_settings()
    metadata = settings.standardized_data_
    records = read_metadata(metadata)

    data_dir = settings._data
    metadata_path = settings.metadata_

    make_data_blocks(records, data_dir, metadata_path)