# Initialize Polaris 

## Requesting and downloading data
A user must give a list of the data of interest that specifies the data they are interested in and will likely analyze and query using Polaris. Each entry on the list specifies the variable, time range, spatial range (including height or similar parameter), and the expected finest resolution needed for that variable. Additionally, a user must specify the repositories they have access to. These are used to generate API calls to the available repositories, and download the data which will then be standardized and ingested into the Polaris system.

## Initial Settings
* Coordinate reference metadata: we use a regular latitude-longitude projections that is referenced by all other native datasets. We refer to this projection as the *common map* $M$.

* The bucket intervals are defined with a half-open interval, where the open side is the larger side. Bucket intervals are defined by one latitude interval and one longitude interval.

* Bucket size:

* The dateline we use is UTC.

* Latitude-Longitude convention: convert all longitude values into the range $[0, 360)$. Some datasets may have longitude values in the range $(-180,180)$ or $(0, 360)$, with different combinations of open and closed boundaries. 
