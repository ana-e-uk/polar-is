"""Aggregate the data blocks to coarser spatial and temporal resolutions.

For every bucket that has one or more (new) blocks,
    Coarsen blocks to the following temporal resolutions: {Hour, Day, Month, Year}
    Store these coarser blocks
    Coarsen blocks spatially by a factor of 2 and a factor of 4
    Store these coarser blocks

For every new temporally coarser block
    Coarsen blocks spatially by a factor of 2 and a factor of 4

"""
from polaris.config import get_settings