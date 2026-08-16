# Interface

The web interface is divided into 3 sections: a column on the right-hand side that contains plots and their specific parameters, a bottom row that goes up to the right-hand column with the main parameters that define the *data object* and the general controls of the interface, and the leftover top-left rectangle is initially a map of the world, but becomes a large plot once a query is made.

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