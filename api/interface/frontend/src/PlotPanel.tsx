import { useEffect, useRef } from "react";
import type { Data, Layout } from "plotly.js";
import { loadCoastlines, type CoastlineCoordinates } from "./geoTopology";
import { datasetName, repositoryName, spatialResolutionTitle, variableTitle } from "./titles";
import type { Catalog, QueryResult, ResultGroup } from "./types";

type Props = { result: QueryResult | null; loading: boolean; catalog: Catalog };
type ValueRange = { minimum: number; maximum: number };
type SpatialCell = {
  value: number;
  label: string;
  matches: boolean;
  latitudes: number[];
  longitudes: number[];
  latitude: number;
  longitude: number;
};

const VIRIDIS = [
  "#440154", "#482878", "#3e4989", "#31688e", "#26828e",
  "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725",
];

const isAreaGroup = (group: ResultGroup) =>
  group.data.kind === "heatmap" || group.data.kind === "find-area";

const isProjectedGroup = (group: ResultGroup) =>
  group.grid?.type === "projected"
  || group.grid_mapping?.grid_mapping_name === "lambert_conformal_conic";

function sourceName(group: ResultGroup, catalog: Catalog): string {
  const details = Object.values(group.source.additional_parameters).join(", ");
  const dataset = datasetName(catalog, group.source.repository, group.source.dataset);
  return `${dataset}${details ? ` · ${details}` : ""}`;
}

function selectedDataset(group: ResultGroup, catalog: Catalog) {
  return catalog.repositories
    .find((repository) => repository.name === group.source.repository)
    ?.datasets.find((dataset) => dataset.name === group.source.dataset);
}

function interpolateColor(first: string, second: string, amount: number): string {
  const channel = (color: string, offset: number) => Number.parseInt(color.slice(offset, offset + 2), 16);
  const value = (offset: number) => Math.round(
    channel(first, offset) + (channel(second, offset) - channel(first, offset)) * amount,
  );
  return `rgb(${value(1)}, ${value(3)}, ${value(5)})`;
}

function viridisColor(value: number, minimum: number, maximum: number): string {
  if (maximum <= minimum) return interpolateColor(VIRIDIS[0], VIRIDIS[1], 0.5);
  const normalized = Math.max(0, Math.min(1, (value - minimum) / (maximum - minimum)));
  const position = normalized * (VIRIDIS.length - 1);
  const lower = Math.min(Math.floor(position), VIRIDIS.length - 2);
  return interpolateColor(VIRIDIS[lower], VIRIDIS[lower + 1], position - lower);
}

function coordinateTrace(
  projected: boolean,
  longitudes: Array<number | null>,
  latitudes: Array<number | null>,
  trace: Omit<Data, "type">,
): Data {
  return projected
    ? { ...trace, type: "scattergeo", lon: longitudes, lat: latitudes } as Data
    : { ...trace, type: "scatter", x: longitudes, y: latitudes } as Data;
}

function projectedHeatmapTrace(
  cells: SpatialCell[],
  group: ResultGroup,
  catalog: Catalog,
  range: ValueRange,
): Data {
  // Fine CARRA selections can contain tens of thousands of cells. Plotly
  // cannot initialize that many independent scattergeo traces, so represent
  // cells with similar colors as GeoJSON MultiPolygons in one choropleth.
  // Hover stays exact because a separate center-marker trace retains every
  // original value.
  const binCount = 256;
  const span = range.maximum - range.minimum;
  const bins = Array.from({ length: binCount }, () => [] as SpatialCell[]);
  cells.forEach((cell) => {
    const normalized = span <= 0 ? 0 : (cell.value - range.minimum) / span;
    const index = Math.max(0, Math.min(binCount - 1, Math.floor(normalized * binCount)));
    bins[index].push(cell);
  });
  const populated = bins.flatMap((members, index) => {
    if (!members.length) return [];
    const id = `color-bin-${index}`;
    const representativeValue = span <= 0
      ? range.minimum
      : range.minimum + ((index + 0.5) / binCount) * span;
    return [{
      id,
      value: representativeValue,
      feature: {
        type: "Feature",
        id,
        properties: {},
        geometry: {
          type: "MultiPolygon",
          coordinates: members.map((cell) => [[
            ...cell.longitudes.map((longitude, corner) => [longitude, cell.latitudes[corner]]),
            [cell.longitudes[0], cell.latitudes[0]],
          ]]),
        },
      },
    }];
  });
  return {
    type: "choropleth",
    geojson: { type: "FeatureCollection", features: populated.map((item) => item.feature) },
    featureidkey: "id",
    locations: populated.map((item) => item.id),
    z: populated.map((item) => item.value),
    zmin: range.minimum,
    zmax: range.maximum === range.minimum ? range.minimum + 1 : range.maximum,
    autocolorscale: false,
    colorscale: "Viridis",
    showscale: true,
    colorbar: { title: { text: group.units ?? "Value" }, thickness: 14 },
    marker: { line: { color: "rgba(255,255,255,0.18)", width: 0.15 } },
    name: sourceName(group, catalog),
    hoverinfo: "skip",
    showlegend: false,
  } as Data;
}

function areaTraces(group: ResultGroup, catalog: Catalog, range: ValueRange): Data[] {
  const data = group.data;
  if (data.kind !== "heatmap" && data.kind !== "find-area") return [];
  const projected = isProjectedGroup(group);
  const cells: SpatialCell[] = data.values.flatMap((value, index) => {
    const latitude = data.latitudes[index];
    const longitude = data.longitudes[index];
    const latitudes = data.corner_latitudes[index];
    const longitudes = data.corner_longitudes[index];
    if (value === null || latitude === null || longitude === null
        || latitudes?.some((item) => item === null)
        || longitudes?.some((item) => item === null)) return [];
    return [{
      value,
      label: `${latitude.toFixed(3)}°, ${longitude.toFixed(3)}°`,
      matches: data.matches?.[index] ?? false,
      latitudes: latitudes as number[],
      longitudes: longitudes as number[],
      latitude,
      longitude,
    }];
  });
  if (!cells.length) return [];

  // A separate path per cell prevents Plotly from filling the shared envelope
  // of null-separated polygons with only the first cell's color.
  const traces: Data[] = projected
    ? [projectedHeatmapTrace(cells, group, catalog, range)]
    : cells.map((cell) => coordinateTrace(
      false,
      [...cell.longitudes, cell.longitudes[0]],
      [...cell.latitudes, cell.latitudes[0]],
      {
        mode: "lines",
        fill: "toself",
        fillcolor: viridisColor(cell.value, range.minimum, range.maximum),
        connectgaps: false,
        line: { color: "rgba(255,255,255,0.25)", width: 0.25 },
        hoverinfo: "skip",
        showlegend: false,
      } as Omit<Data, "type">,
    ));

  traces.push(coordinateTrace(
    projected,
    cells.map((cell) => cell.longitude),
    cells.map((cell) => cell.latitude),
    {
      mode: "markers",
      text: cells.map((cell) => cell.label),
      customdata: cells.map((cell) => cell.value),
      name: sourceName(group, catalog),
      marker: { size: 12, color: "rgba(255,255,255,0.001)" },
      hovertemplate: `%{text}<br>%{customdata} ${group.units ?? ""}<extra>${sourceName(group, catalog)}</extra>`,
      showlegend: false,
    } as Omit<Data, "type">,
  ));

  if (!projected) {
    traces.push(coordinateTrace(
      false,
      [cells[0].longitude, cells[0].longitude],
      [cells[0].latitude, cells[0].latitude],
      {
        mode: "markers",
        marker: {
          size: 0,
          opacity: 0,
          color: [range.minimum, range.maximum],
          autocolorscale: false,
          colorscale: "Viridis",
          cmin: range.minimum,
          cmax: range.maximum === range.minimum ? range.minimum + 1 : range.maximum,
          showscale: true,
          colorbar: { title: { text: group.units ?? "Value" }, thickness: 14 },
        },
        hoverinfo: "skip",
        showlegend: false,
      } as Omit<Data, "type">,
    ));
  }

  const matches = cells.filter((cell) => cell.matches);
  if (data.kind === "find-area" && matches.length) {
    const latitudes: Array<number | null> = [];
    const longitudes: Array<number | null> = [];
    matches.forEach((cell) => {
      latitudes.push(...cell.latitudes, cell.latitudes[0], null);
      longitudes.push(...cell.longitudes, cell.longitudes[0], null);
    });
    traces.push(coordinateTrace(projected, longitudes, latitudes, {
      mode: "lines",
      name: "Matches filter",
      hoverinfo: "skip",
      line: { color: "#dc2626", width: 2.5 },
    } as Omit<Data, "type">));
  }
  return traces;
}

function coastlineTrace(projected: boolean, coastlines: CoastlineCoordinates): Data {
  return coordinateTrace(projected, coastlines.longitudes, coastlines.latitudes, {
    mode: "lines",
    line: { color: "#344e5c", width: 1.2 },
    hoverinfo: "skip",
    showlegend: false,
  } as Omit<Data, "type">);
}

function numericExtent(values: number[]): [number, number] | undefined {
  if (!values.length) return undefined;
  return values.reduce<[number, number]>(
    ([minimum, maximum], value) => [Math.min(minimum, value), Math.max(maximum, value)],
    [values[0], values[0]],
  );
}

function paddedRange(values: number[]): [number, number] | undefined {
  const extent = numericExtent(values);
  if (!extent) return undefined;
  const [minimum, maximum] = extent;
  const padding = Math.max((maximum - minimum) * 0.025, 0.05);
  return [minimum - padding, maximum + padding];
}

function projectionLayout(
  group: ResultGroup,
  longitudes: number[],
  latitudes: number[],
): Partial<Layout>["geo"] {
  const mapping = group.grid_mapping;
  const parallels = mapping?.standard_parallel;
  const standardParallels = Array.isArray(parallels)
    ? parallels.slice(0, 2)
    : parallels === undefined ? undefined : [parallels, parallels];
  const centralLongitude = mapping?.longitude_of_central_meridian ?? 0;
  const displayedCentralLongitude = ((centralLongitude + 180) % 360 + 360) % 360 - 180;
  const projectionOrigin = mapping?.latitude_of_projection_origin ?? 0;
  return {
    projection: {
      type: "conic conformal",
      parallels: standardParallels,
      rotation: {
        // Plotly/D3 rotation is the inverse of the CF central meridian.
        lon: -displayedCentralLongitude,
        lat: 0,
      },
    },
    center: { lon: displayedCentralLongitude, lat: projectionOrigin },
    showland: true,
    landcolor: "#e7eef2",
    showocean: true,
    oceancolor: "#f3f8fa",
    showcoastlines: false,
    showcountries: false,
    showframe: true,
    framecolor: "#506878",
    framewidth: 1,
    lonaxis: { showgrid: true, gridcolor: "#aebfca", dtick: 10, range: paddedRange(longitudes) },
    lataxis: { showgrid: true, gridcolor: "#aebfca", dtick: 5, range: paddedRange(latitudes) },
  };
}

function SpatialPlot({ group, catalog, range }: { group: ResultGroup; catalog: Catalog; range: ValueRange }) {
  const plotRef = useRef<HTMLDivElement>(null);
  const projected = isProjectedGroup(group);

  useEffect(() => {
    if (!plotRef.current) return;
    let disposed = false;
    let plotly: typeof import("plotly.js-dist-min").default | null = null;
    const element = plotRef.current;
    const data = group.data;
    if (data.kind !== "heatmap" && data.kind !== "find-area") return;
    const longitudes = data.corner_longitudes.flat().filter((value): value is number => value !== null);
    const latitudes = data.corner_latitudes.flat().filter((value): value is number => value !== null);
    const traces = areaTraces(group, catalog, range);
    const hasMatches = data.kind === "find-area" && data.matches?.some(Boolean);
    const layout: Partial<Layout> = {
      autosize: true,
      margin: projected
        ? { l: 12, r: 54, t: 8, b: hasMatches ? 52 : 16 }
        : { l: 58, r: 54, t: 8, b: hasMatches ? 76 : 54 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#f7fafc",
      font: { family: "Inter, ui-sans-serif, system-ui", color: "#17324d", size: 12 },
      showlegend: Boolean(hasMatches),
      legend: { orientation: "h", x: 0, y: -0.18, yanchor: "top" },
      xaxis: projected ? undefined : {
        title: { text: "Longitude" },
        gridcolor: "#b8c8d3",
        showline: true,
        mirror: true,
        ticks: "outside",
        range: paddedRange(longitudes),
      },
      yaxis: projected ? undefined : {
        title: { text: "Latitude" },
        gridcolor: "#b8c8d3",
        showline: true,
        mirror: true,
        ticks: "outside",
        range: paddedRange(latitudes),
        scaleanchor: "x",
        scaleratio: 1,
      },
      geo: projected ? projectionLayout(group, longitudes, latitudes) : undefined,
    };

    const coastlineRequest = loadCoastlines().catch(() => null);
    void Promise.all([import("plotly.js-dist-min"), coastlineRequest]).then(([{ default: Plotly }, coastlines]) => {
      if (disposed) return;
      plotly = Plotly;
      if (coastlines) traces.push(coastlineTrace(projected, coastlines));
      Plotly.react(element, traces, layout, {
        responsive: true,
        displaylogo: false,
        topojsonURL: `${import.meta.env.BASE_URL}topojson/`,
      });
    });
    return () => {
      disposed = true;
      if (plotly) plotly.purge(element);
    };
  }, [catalog, group, projected, range.maximum, range.minimum]);

  const resolution = spatialResolutionTitle(catalog, selectedDataset(group, catalog), group.coarseness_factor);
  return (
    <article className="spatial-plot-card">
      <header className="spatial-plot-heading">
        <h3>{sourceName(group, catalog)}</h3>
        <p>{repositoryName(catalog, group.source.repository)} · {resolution}</p>
      </header>
      <div className="spatial-plot" ref={plotRef} />
    </article>
  );
}

function TimePlot({ result, catalog }: { result: QueryResult; catalog: Catalog }) {
  const plotRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!plotRef.current) return;
    let disposed = false;
    let plotly: typeof import("plotly.js-dist-min").default | null = null;
    const element = plotRef.current;
    const groups = result.groups;
    const multipleGroups = groups.length > 1;
    const traces: Data[] = groups.flatMap((group, groupIndex) => {
      const data = group.data;
      if (data.kind !== "timeseries" && data.kind !== "find-time") return [];
      const timeTraces: Data[] = [{
        type: "scatter", mode: "lines+markers", x: data.timestamps, y: data.values,
        name: sourceName(group, catalog), line: { width: 2 }, marker: { size: 5 },
      } as Data];
      if (data.kind === "find-time" && data.matches) {
        timeTraces.push({
          type: "scatter", mode: "markers",
          x: data.timestamps.filter((_, index) => data.matches?.[index]),
          y: data.values.filter((_, index) => data.matches?.[index]),
          name: "Matches filter", showlegend: groupIndex === 0,
          marker: { color: "#dc2626", size: 10, line: { color: "white", width: 1 } },
        } as Data);
      }
      return timeTraces;
    });
    const units = Array.from(new Set(groups.map((group) => group.units).filter(Boolean)));
    const variable = variableTitle(catalog, groups[0].source.variable);
    const layout: Partial<Layout> = {
      autosize: true,
      margin: { l: 62, r: 28, t: 22, b: multipleGroups ? 128 : 82 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#f7fafc",
      font: { family: "Inter, ui-sans-serif, system-ui", color: "#17324d", size: 13 },
      legend: { orientation: "h", x: 0, y: multipleGroups ? -0.36 : -0.24, yanchor: "top" },
      xaxis: { title: { text: "Time", standoff: 12 }, gridcolor: "#dbe6ef" },
      yaxis: {
        title: { text: units.length === 1 ? `${variable} (${units[0]})` : variable },
        gridcolor: "#dbe6ef",
      },
    };
    const first = groups[0].data;
    if (first.kind === "find-time" && first.filter_value !== undefined) {
      layout.shapes = [{
        type: "line", xref: "paper", x0: 0, x1: 1,
        y0: first.filter_value, y1: first.filter_value,
        line: { color: "#dc2626", width: 1.5, dash: "dash" },
      }];
    }
    void import("plotly.js-dist-min").then(({ default: Plotly }) => {
      if (disposed) return;
      plotly = Plotly;
      Plotly.react(element, traces, layout, { responsive: true, displaylogo: false });
    });
    return () => {
      disposed = true;
      if (plotly) plotly.purge(element);
    };
  }, [catalog, result]);

  return <section className="result-panel"><div className="plot" ref={plotRef} /></section>;
}

function valueRange(groups: ResultGroup[], group: ResultGroup): ValueRange {
  const values = groups
    .filter((candidate) => candidate.units === group.units)
    .flatMap((candidate) => {
      const data = candidate.data;
      if (data.kind !== "heatmap" && data.kind !== "find-area") return [];
      return data.values.filter((value): value is number => value !== null);
    });
  const extent = numericExtent(values);
  if (!extent) return { minimum: 0, maximum: 1 };
  return { minimum: extent[0], maximum: extent[1] };
}

export default function PlotPanel({ result, loading, catalog }: Props) {
  if (loading) return <section className="result-panel state-panel"><div className="spinner" /><h2>Reading Polar-is storage</h2><p>The query may take a moment for a large region or fine resolution.</p></section>;
  if (!result) return <section className="result-panel state-panel"><div className="empty-orbit" aria-hidden="true" /><h2>No result yet</h2><p>Select a region and data object, then run a query.</p></section>;
  if (!result.groups.length) return <section className="result-panel state-panel"><h2>No matching data</h2><p>Try another region, time interval, or resolution. Review the warnings below for details.</p></section>;
  if (result.function === "get-data") return <section className="result-panel state-panel"><h2>Data is ready</h2><p>The query returned {result.groups.reduce((sum, group) => sum + (group.data.kind === "get-data" ? group.data.cell_count : 0), 0).toLocaleString()} spatial cells. Use the download links below to save the NetCDF results.</p></section>;

  const areaGroups = result.groups.filter(isAreaGroup);
  if (areaGroups.length) {
    return (
      <section className="result-panel spatial-result-panel">
        <div className="spatial-plot-grid">
          {areaGroups.map((group) => (
            <SpatialPlot key={group.group_id} group={group} catalog={catalog} range={valueRange(areaGroups, group)} />
          ))}
        </div>
      </section>
    );
  }
  return <TimePlot result={result} catalog={catalog} />;
}
