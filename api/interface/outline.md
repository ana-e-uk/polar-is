# Interface

Below is an overview of what the interface will support in its complete version. The web interface is divided into 3 sections: a column on the right-hand side that contains plots and their specific parameters, a bottom row that goes up to the right-hand column with the main parameters that define the *data object* and the general controls of the interface, and the leftover top-left rectangle is initially a map of the world, but becomes a large plot once a query is made.

## **Right-hand Side Plots Column**
The plots column should be divided into 3 rows. These rows will have two parameter drop-down menu buttons at the top that control the plot type (heatmap, timeseries, filtering, or *statistics*) and the variable (set of variables available given the chosen dataset). Below these buttons is the chosen plot for the selected variable. 

Each row is independent and can show the same plot type and variable, or a different plot type and variable. However, they are all modified by the main controls.

The *statistics* plot type will show a histogram and some basic statistics about the selected variable. These will have several parameters to change, like bin count, statistic to show (mean, median, max, min), etc.. The filtering plot types will have parameters defining the filter and editing the axes. The standard plots (heatmap, timeseries) will also have axes editing parameters.

## **Main Parameter Bottom Row**
The main paremeters controlling the *data object* queried from storage are in this bottom row: the dataset, variable, time range, region, and other additional variables that may be required by the dataset. The dataset is a drop-down menu that has all the available datasets. If a dataset is chosen, the variables in the variable drop-down menus in the bottom row as well as the right-hand side column rows are subset to only be the variables of that dataset. If no dataset is chosen, only pre-defined groups of variables are shown as options (e.g., all temperature variables from all datasets that may be in the "Temperature" group). The time range specifies the year, month, day, and optionally hour of the time range. The region can be specified by drawing a rectangle or polygon on the map in the left-hand section of the interface, or using the North, South, East, West input regions. A section for additional parameters will be populated with any additional inputs needed for a dataset/variable (e.g., height, variable 2).

There are three general buttons that show the available data (Available Data), send the query request (Query), and download (Download) the specified data when clicked. The download button can download the data or the plots chosen.

## **Top Left-hand Side Map/Plot**
The section on the left is initially a map of the world that is an option for users to define the spatial region of interest by drawing a rectangle on the desired area. Once the "Query" button is clicked, the map will become a plot like those in the right-hand column, just larger. 

## Default settings
When a session of the web interface is started, all the plots and main parameters will be blank, but the default plot types will be: heatmap for the top left-hand, timeseries for the top right-hand column, statistics for the middle right-hand column, and statistics for the bottom right-hand column with different subparameters selected.

# Interface v.1

This is what the interface will support initially.

The web interface is divided into 3 sections: a column on the right-hand side that contains plots and their specific parameters, a bottom row that goes up to the right-hand column with the main parameters (specs) that define the *data object* and the general controls of the interface, and the leftover top-left rectangle is initially a map of the world, but becomes a large plot once a query is made.

## **Right-hand Side Plots Column**
The plots column should be divided into 3 rows. These rows will have two parameter drop-down menu buttons at the top that control the plot type, i.e., the query function (heatmap, timeseries, find-time, find-area) and specs, e.g. the variable, repository, dataset, dataset-specific parameters. Note the only required spec is the variable. Below these buttons is the chosen function plotted for the selected variable. 

Each row is independent and can show the same function and variable, or a different function and variable. Each time a function and/or variable for a row is changed, this is treated as a query to the backend using the updated inputs for the row and the current selections of the main controls.

The plot legend/axes labels should stay a readable level and take up all its given space in its row. If the region dimensions do not match the dimensions of the row, instead of making it much smaller, switch the axes or change the steps of the axes values to make it fit better.

## **Main Parameter Bottom Row**
The main paremeters controlling the *data object* queried from storage are in this bottom row:  

* the specs: repository, dataset, variable, dataset-specific parameters.
    * OPTIONAL: 
        * the repository filters the dataset options. It is a dropdown menu showing all available repositories and the option "Any" which does not filter the variable options. "Any" is the default option. If a repository is chosen, the dataset options are limited to the datasets within the chosen repository.
        * the dataset filters the variable and resolution options. It is a dropdown menu that has all the available datasets and the option "Any" which does not filter the other parameters. "Any" is the default option. If a dataset is chosen, the variable options are limited to the variables within the chosen dataset.
        * data-specific parameters are shown if the dataset has them. They are optional to specify, because each dataset will have default additional parameter inputs that will be used unless User changes them.
    * REQUIRED: 
        * the variable is required. It is a dropdown menu that has all the available variables (given the optional filtering from dataset/repo). If no repository or dataset are chosen, the query looks for and returns the values for all datasets that have this variable.

* the region: the bounding box of the spatial region the data should cover. User is required to specify min/max lat/lon. The region can be specified by drawing a rectangle on the map in the left-hand section of the interface, or using the North, South, East, West textbox-like inputs.
*  the time interval: the continuous time interval the data should cover at the specified time resolution. User is required to specify start and end of time interval. The start/end specifies the year, month, day, and optionally hour.
* the coarseness factor: the spatial resolution of the data to use. Currently, can offer source (native) spatial resolution, coarsen-2, and coarsen-4 (coarsen-2 and coarsen-4 are the result of the two spatial aggregations/coarsenings). User is required to specify the coarseness factor. The default is coarsen-4.
* the time unit: the temporal resolution of the data to use. Currently, can offer source temporal resolution and all resolutions (coarser than the dataset source resolution) of Hour, Day, Month, Year. User is required to specify the time unit. The default is the coarsest time unit available for the specified dataset/variable.
* the aggregation method - the way the data is aggregated by for a function. Currently, offer mean, max, min. The user must choose between these.
* the function: the result to return. Currently offer timeseries, heatmap, find-area, find-time. User is required to choose one function.
    * If a filtering function is chosen: find-area or find-time, then the following additional parameters are also required by the query: predicate and filter value.


Three action buttons are also part of this bottom section of the interface:

* Available Data: show all the available data in a table that gives: for each repo, dataset, variable set, the continuous bounding box regions and the corresponding continuous time interval for that region, and the source spatial and temporal resolutions.

* Query: send the query request to the backend. This should not send a query to the backend until the required parameters (variable, region, time interval, time unit, aggregation method, function) are chosen. Print a message to pick required parameters. 

* Download: download the specified data when clicked. The download button can download the data or the plots chosen.


## **Top Left-hand Side Map/Plot**
This section is initially a map of the world that users can use to define the spatial region of interest by drawing a rectangle on the desired area. Once the "Query" button is clicked, the map will become a plot like those in the right-hand column, just larger. A button closing the large plot will return the map of the world for a new region to be selected.

## Default settings
When a session of the web interface is initialized, all the plots and main parameters will be blank.