from storage.ingest_data.standardize import standardize
from storage.ingest_data.make_data_blocks import make_data_blocks

from polaris.config import get_settings

def ingest_data():
    """Ingest data."""

    # Read in directory and metadata file paths

    # Check there is enough storage to standardize all downloaded data at once
    
    # Standardize data

    # Split standardized datasets into blocks and store by bucket

    # Aggregate buckets