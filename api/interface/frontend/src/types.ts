export type Region = {
  west: number;
  east: number;
  south: number;
  north: number;
};

export type Dataset = {
  name: string;
  display_name?: string | null;
  variables: string[];
  additional_parameters: Record<string, Array<string | number>>;
  temporal_sampling: string[];
  grid: GridDefinition | null;
  available_products?: AvailableProduct[];
};

export type AvailableProduct = {
  variable: string;
  time_unit: string;
  coarseness_factor: number;
};

export type Repository = {
  name: string;
  display_name?: string | null;
  datasets: Dataset[];
};

export type GridDefinition = {
  type?: string;
  name?: string;
  resolution?: Array<number | string>;
  units?: string;
};

export type FrontendTitles = {
  repository?: Record<string, string>;
  variable?: Record<string, string>;
  resolution?: Record<string, Record<string, Array<number | string>>>;
};

export type Catalog = {
  repositories: Repository[];
  frontend_titles: FrontendTitles;
  coarseness_factors: number[];
  time_units: string[];
  functions: string[];
  aggregation_methods: string[];
};

export type QueryForm = {
  repository: string;
  dataset: string;
  variable: string;
  time_start: string;
  time_end: string;
  region: Region;
  coarseness_factor: number;
  time_unit: string;
  function: string;
  aggregation_method: string;
  additional_parameters: Record<string, string | number>;
  predicate: string;
  filter_value: string;
};

export type AvailabilityRow = {
  repository: string;
  dataset: string;
  variable: string;
  additional_parameters: Record<string, unknown>;
  region: Region;
  time_start: string;
  time_end: string;
  spatial_resolutions: Array<string | number>;
  temporal_resolutions: string[];
};

type TimeData = {
  kind: "timeseries" | "find-time";
  timestamps: string[];
  values: Array<number | null>;
  matches?: boolean[];
  predicate?: string;
  filter_value?: number;
};

type AreaData = {
  kind: "heatmap" | "find-area";
  grid_id: string;
  latitudes: Array<Array<number | null>>;
  longitudes: Array<Array<number | null>>;
  grid_y_indices: number[];
  grid_x_indices: number[];
  projection_x?: Array<number | null>;
  projection_y?: Array<number | null>;
  values: Array<Array<number | null>>;
  matches?: boolean[][];
  predicate?: string;
  filter_value?: number;
};

type DownloadData = {
  kind: "get-data";
  timestamps: string[];
  grid_shape: [number, number];
};

export type ResultGroup = {
  group_id: string;
  source: {
    repository: string;
    dataset: string;
    variable: string;
    additional_parameters: Record<string, unknown>;
  };
  grid: GridDefinition | null;
  grid_mapping: {
    grid_mapping_name?: string;
    standard_parallel?: number | number[];
    longitude_of_central_meridian?: number;
    latitude_of_projection_origin?: number;
    false_easting?: number;
    false_northing?: number;
    earth_radius?: number;
    semi_major_axis?: number;
    inverse_flattening?: number;
  } | null;
  coarseness_factor: number;
  units: string | null;
  warnings: string[];
  coverage: { hit_count: number; miss_count: number };
  download_url: string;
  data: TimeData | AreaData | DownloadData;
};

export type QueryResult = {
  query_id: string;
  function: string;
  warnings: string[];
  unmatched_miss_count: number;
  groups: ResultGroup[];
};

export type PlotLayout = "grid" | "large";

export type PlotSnapshot = {
  id: string;
  result: QueryResult;
  query: QueryForm;
  colorRange?: { minimum: number; maximum: number };
};

export type QueryJob = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | "expired";
  status_url: string;
  result?: QueryResult;
  error?: { code: string; message: string };
  jobs_ahead?: number;
};

export type ServiceStatus = {
  access_mode: "anonymous" | "token";
  running_jobs: number;
  queued_jobs: number;
  queue_capacity: number;
};
