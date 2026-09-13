export type Region = {
  west: number;
  east: number;
  south: number;
  north: number;
};

export type Dataset = {
  name: string;
  variables: string[];
  additional_parameters: Record<string, Array<string | number>>;
  temporal_sampling: string[];
  grid: Record<string, unknown> | null;
};

export type Repository = {
  name: string;
  datasets: Dataset[];
};

export type Catalog = {
  repositories: Repository[];
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
};

type TimeData = {
  kind: "timeseries" | "find-time";
  timestamps: string[];
  values: Array<number | null>;
  matches?: boolean[];
};

type AreaData = {
  kind: "heatmap" | "find-area";
  latitudes: Array<number | null>;
  longitudes: Array<number | null>;
  values: Array<number | null>;
  matches?: boolean[];
};

type DownloadData = {
  kind: "get-data";
  timestamps: string[];
  cell_count: number;
};

export type ResultGroup = {
  group_id: string;
  source: {
    repository: string;
    dataset: string;
    variable: string;
    additional_parameters: Record<string, unknown>;
  };
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

