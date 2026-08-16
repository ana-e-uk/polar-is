# Querying data

Given a query from the command line or web interface API, find the requested data and return the result of requested computation. The query gives parameters of what functions need to be run and what plots the user is requesting.

## Query Parameters:

### Input:

**Required Input**
A query needs to contain the following input:

1. A dataset. The dataset options are: each dataset independently, any available dataset combined to give an estimate answer, and any available datasets that provide an answer, but separately (not combined). 
2. A variable. Variable options are: each variable of each dataset, variables that are defined as the same across different datasets combined, and variable shared amongst a set of datasets but treated independently. 

**Optional Input**
A query may also specify: 

1. The \emph{height} of the measurements. The default is set at Earth surface level.
2. The temporal and spatial resolutions, which default to Day and $0.5^{\circ}$. The temporal options are the native resolution of the data (usually the finest), hour, day, month, and year. The spatial options are "0", the non-aggregated (native) data resolution, "1" the data coarsened by a factor of two, and "2", the data coarsened by a factor of 4. This will be different for each dataset, which is why it is just defined with indexing the number of times the data is coarsened.
3. The time range, which defaults to all the time range of the chosen dataset and variable.
4. A spatial range in the form of a rectangular bounding box. The bounding box is defined by the values `[min_lon, max_lon, min_lat, max_lat]`. The default is the whole world.
5. Additional dataset specific parameters that are also dimensions, for example pressure level, sensor band, ensemble member, etc..
6. The aggregate function to use out of minimum, maximum, and mean aggregates. If none is specified, the default is the mean.
7. The plots to return, defaulting to time series and heatmap.
8. A filter value and predicate that specify a filter query. The default is none. 
9. The grid type that the user wants the data in. The default is the native data grid for individual datasets, and the common grid for combined data.
10. Additional parameters that may be required by a dataset or variable. This defaults to none.