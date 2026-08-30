"""Aggregate the data blocks to coarser spatial and temporal resolutions to get spatio-temporal hierarchy:

(Fine, Coarse) x (unique dataset temporal resolutions)

1. Coarsen native data by time to make all the "Fine" groups
2. Split Fine group data into blocks using original buckets

3. Coarsen Fine groups by space to get "Coarse" groups
4. Split Coarse group data into blocks using large buckets

"""
from polaris.config import get_settings