# PolarIS API

The two APIs provided for PolarIS, a command line API and web-based interface, can be used to query the data managed by PolarIS storage. The goal is to make it easy for scientists to explore the data they have. The storage management uses the aggregated data to answer the queries from scientists quickly and interactively.

Both APIs work by defining a *data object* that defines the spatial-temporal region of the world, the variables and resolution of the data that is of interest. This data can be downloaded or explored through heatmaps, time series, or filtering queries.

Through both APIs, a user can:

1. Get Raster - Choose a *data object* (a variable for a spatio-temporal region at a specific resolution) to download.

2. Timeseries - *Data object* data will be used to plot a timeseires by aggregating all spatial points together by timestamp.

3. Heatmap - *Data object* data will be used to plot a heatmap by aggregating all temporal points together by location.

4. Find time - Data in a *data object* will be filtered to the times that fulfill given requirement.

5. Find area - Data in a *data object* will be filtered to the locations that fulfill given requirement.