import { useEffect, useRef } from "react";
import type { Data, Layout } from "plotly.js";
import { loadCoastlines, type CoastlineCoordinates } from "./geoTopology";
import { datasetName, fallbackTitle, repositoryName, spatialResolutionTitle, variableTitle } from "./titles";
import type { Catalog, PlotLayout, PlotSnapshot, QueryForm, QueryResult, ResultGroup } from "./types";

type Props = {
  result: QueryResult | null;
  query: QueryForm | null;
  loading: boolean;
  catalog: Catalog;
  pinnedPlots: PlotSnapshot[];
  layout: PlotLayout;
  useSharedScale: boolean;
  onPin: (plot: PlotSnapshot) => void;
  onUnpin: (id: string) => void;
};
type ValueRange = { minimum: number; maximum: number };
type SpatialCell = {
  value: number;
  matches: boolean;
  latitudes: number[];
  longitudes: number[];
  latitude: number;
  longitude: number;
  projectionX: number | null;
  projectionY: number | null;
  gridX: number;
  gridY: number;
};
type ProjectedGrid = {
  trace: Data;
  xRange: [number, number];
  yRange: [number, number];
  dx: number;
  dy: number;
};

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

function coordinateSpacing(values: number[]): number {
  if (values.length < 2) return 1;
  const differences = values.slice(1)
    .map((value, index) => Math.abs(value - values[index]))
    .filter((value) => value > 0)
    .sort((left, right) => left - right);
  return differences[Math.floor(differences.length / 2)] ?? 1;
}

function projectedHeatmap(
  cells: SpatialCell[],
  group: ResultGroup,
  catalog: Catalog,
  range: ValueRange,
): ProjectedGrid {
  // CARRA is regular in its native Lambert coordinates. A two-dimensional
  // heatmap preserves every exact cell value without asking Plotly to create
  // tens of thousands of SVG polygon paths.
  const projectedCells = cells.filter(
    (cell): cell is SpatialCell & { projectionX: number; projectionY: number } =>
      cell.projectionX !== null && cell.projectionY !== null,
  );
  if (!projectedCells.length) throw new Error("Projected cells are missing projection_x/projection_y coordinates");
  const xByIndex = new Map<number, number>();
  const yByIndex = new Map<number, number>();
  projectedCells.forEach((cell) => {
    xByIndex.set(cell.gridX, cell.projectionX);
    yByIndex.set(cell.gridY, cell.projectionY);
  });
  const columns = [...xByIndex.entries()].sort((left, right) => left[1] - right[1]);
  const rows = [...yByIndex.entries()].sort((left, right) => left[1] - right[1]);
  const columnPositions = new Map(columns.map(([index], position) => [index, position]));
  const rowPositions = new Map(rows.map(([index], position) => [index, position]));
  const values: Array<Array<number | null>> = Array.from(
    { length: rows.length },
    () => Array.from({ length: columns.length }, () => null),
  );
  const hover: Array<Array<[number, number] | null>> = Array.from(
    { length: rows.length },
    () => Array.from({ length: columns.length }, () => null),
  );
  projectedCells.forEach((cell) => {
    const row = rowPositions.get(cell.gridY);
    const column = columnPositions.get(cell.gridX);
    if (row === undefined || column === undefined) return;
    values[row][column] = cell.value;
    hover[row][column] = [cell.latitude, cell.longitude];
  });
  const x = columns.map(([, coordinate]) => coordinate);
  const y = rows.map(([, coordinate]) => coordinate);
  const dx = coordinateSpacing(x);
  const dy = coordinateSpacing(y);
  return {
    trace: {
      type: "heatmap",
      x,
      y,
      z: values,
      customdata: hover,
      zmin: range.minimum,
      zmax: range.maximum === range.minimum ? range.minimum + 1 : range.maximum,
      autocolorscale: false,
      colorscale: "Viridis",
      showscale: true,
      colorbar: { title: { text: group.units ?? "Value" }, thickness: 14 },
      zsmooth: false,
      name: sourceName(group, catalog),
      hovertemplate: `%{customdata[0]:.3f}°, %{customdata[1]:.3f}°<br>%{z} ${group.units ?? ""}<extra>${sourceName(group, catalog)}</extra>`,
      showlegend: false,
    } as Data,
    xRange: [x[0] - dx / 2, x[x.length - 1] + dx / 2],
    yRange: [y[0] - dy / 2, y[y.length - 1] + dy / 2],
    dx,
    dy,
  };
}

function rectilinearHeatmapTrace(
  group: ResultGroup,
  catalog: Catalog,
  range: ValueRange,
): Data {
  const data = group.data;
  if (data.kind !== "heatmap" && data.kind !== "find-area") {
    throw new Error("A rectilinear heatmap trace requires spatial data");
  }
  const columns = new Map<number, number>();
  const rows = new Map<number, number>();
  data.grid_x_indices.forEach((gridIndex, index) => {
    const longitude = data.longitudes[index];
    if (longitude !== null) columns.set(gridIndex, longitude);
  });
  data.grid_y_indices.forEach((gridIndex, index) => {
    const latitude = data.latitudes[index];
    if (latitude !== null) rows.set(gridIndex, latitude);
  });
  const orderedColumns = [...columns.entries()].sort((left, right) => left[1] - right[1]);
  const orderedRows = [...rows.entries()].sort((left, right) => left[1] - right[1]);
  const columnPositions = new Map(orderedColumns.map(([index], position) => [index, position]));
  const rowPositions = new Map(orderedRows.map(([index], position) => [index, position]));
  const values: Array<Array<number | null>> = Array.from(
    { length: orderedRows.length },
    () => Array.from({ length: orderedColumns.length }, () => null),
  );
  data.values.forEach((value, index) => {
    const row = rowPositions.get(data.grid_y_indices[index]);
    const column = columnPositions.get(data.grid_x_indices[index]);
    if (row !== undefined && column !== undefined) values[row][column] = value;
  });
  return {
    type: "heatmap",
    x: orderedColumns.map(([, longitude]) => longitude),
    y: orderedRows.map(([, latitude]) => latitude),
    z: values,
    zmin: range.minimum,
    zmax: range.maximum === range.minimum ? range.minimum + 1 : range.maximum,
    autocolorscale: false,
    colorscale: "Viridis",
    showscale: true,
    colorbar: { title: { text: group.units ?? "Value" }, thickness: 14 },
    xgap: 0.35,
    ygap: 0.35,
    zsmooth: false,
    name: sourceName(group, catalog),
    hovertemplate: `%{y:.3f}°, %{x:.3f}°<br>%{z} ${group.units ?? ""}<extra>${sourceName(group, catalog)}</extra>`,
    showlegend: false,
  } as Data;
}

type AreaPlot = { traces: Data[]; cells: SpatialCell[]; projectedGrid?: ProjectedGrid };

function areaPlot(group: ResultGroup, catalog: Catalog, range: ValueRange): AreaPlot {
  const data = group.data;
  if (data.kind !== "heatmap" && data.kind !== "find-area") return { traces: [], cells: [] };
  const projected = isProjectedGroup(group);
  const cells: SpatialCell[] = data.values.flatMap((value, index) => {
    const latitude = data.latitudes[index];
    const longitude = data.longitudes[index];
    const latitudes = data.corner_latitudes[index];
    const longitudes = data.corner_longitudes[index];
    if (value === null || latitude === null || longitude === null
        || !latitudes || !longitudes || latitudes.length < 3 || longitudes.length < 3
        || latitudes.some((item) => item === null)
        || longitudes.some((item) => item === null)) return [];
    return [{
      value,
      matches: data.matches?.[index] ?? false,
      latitudes: latitudes as number[],
      longitudes: longitudes as number[],
      latitude,
      longitude,
      projectionX: data.projection_x?.[index] ?? null,
      projectionY: data.projection_y?.[index] ?? null,
      gridX: data.grid_x_indices[index],
      gridY: data.grid_y_indices[index],
    }];
  });
  if (!cells.length) return { traces: [], cells: [] };

  const projectedGrid = projected ? projectedHeatmap(cells, group, catalog, range) : undefined;
  const traces: Data[] = projectedGrid
    ? [projectedGrid.trace]
    : [rectilinearHeatmapTrace(group, catalog, range)];

  const matches = cells.filter((cell) => cell.matches);
  if (data.kind === "find-area" && matches.length) {
    const vertical: Array<number | null> = [];
    const horizontal: Array<number | null> = [];
    if (projectedGrid) {
      matches.forEach((cell) => {
        if (cell.projectionX === null || cell.projectionY === null) return;
        const left = cell.projectionX - projectedGrid.dx / 2;
        const right = cell.projectionX + projectedGrid.dx / 2;
        const bottom = cell.projectionY - projectedGrid.dy / 2;
        const top = cell.projectionY + projectedGrid.dy / 2;
        horizontal.push(left, right, right, left, left, null);
        vertical.push(bottom, bottom, top, top, bottom, null);
      });
    } else {
      matches.forEach((cell) => {
        vertical.push(...cell.latitudes, cell.latitudes[0], null);
        horizontal.push(...cell.longitudes, cell.longitudes[0], null);
      });
    }
    traces.push(coordinateTrace(false, horizontal, vertical, {
      mode: "lines",
      name: "Matches filter",
      hoverinfo: "skip",
      line: { color: "#dc2626", width: 2.5 },
    } as Omit<Data, "type">));
  }
  return { traces, cells, projectedGrid };
}

function coastlineTrace(projected: boolean, coastlines: CoastlineCoordinates): Data {
  return coordinateTrace(projected, coastlines.longitudes, coastlines.latitudes, {
    mode: "lines",
    line: { color: "#344e5c", width: 1.2 },
    hoverinfo: "skip",
    showlegend: false,
  } as Omit<Data, "type">);
}

function lambertProject(group: ResultGroup, longitude: number, latitude: number): [number, number] | null {
  const mapping = group.grid_mapping;
  if (!mapping || mapping.grid_mapping_name !== "lambert_conformal_conic") return null;
  const rawParallels = mapping.standard_parallel;
  const parallels = Array.isArray(rawParallels)
    ? rawParallels
    : rawParallels === undefined ? [] : [rawParallels];
  if (!parallels.length) return null;
  const toRadians = Math.PI / 180;
  const first = parallels[0] * toRadians;
  const second = (parallels[1] ?? parallels[0]) * toRadians;
  const origin = (mapping.latitude_of_projection_origin ?? 0) * toRadians;
  const centralMeridian = (mapping.longitude_of_central_meridian ?? 0) * toRadians;
  const phi = latitude * toRadians;
  let lambda = longitude * toRadians;
  while (lambda - centralMeridian > Math.PI) lambda -= 2 * Math.PI;
  while (lambda - centralMeridian < -Math.PI) lambda += 2 * Math.PI;
  const n = Math.abs(first - second) < 1e-12
    ? Math.sin(first)
    : Math.log(Math.cos(first) / Math.cos(second))
      / Math.log(
        Math.tan(Math.PI / 4 + second / 2)
        / Math.tan(Math.PI / 4 + first / 2),
      );
  const radius = mapping.earth_radius ?? mapping.semi_major_axis;
  if (!radius || !Number.isFinite(n) || Math.abs(n) < 1e-12) return null;
  const f = Math.cos(first) * Math.pow(Math.tan(Math.PI / 4 + first / 2), n) / n;
  const rho = radius * f / Math.pow(Math.tan(Math.PI / 4 + phi / 2), n);
  const rhoOrigin = radius * f / Math.pow(Math.tan(Math.PI / 4 + origin / 2), n);
  const theta = n * (lambda - centralMeridian);
  const x = (mapping.false_easting ?? 0) + rho * Math.sin(theta);
  const y = (mapping.false_northing ?? 0) + rhoOrigin - rho * Math.cos(theta);
  return Number.isFinite(x) && Number.isFinite(y) ? [x, y] : null;
}

function niceInterval(span: number): number {
  const candidates = [0.25, 0.5, 1, 2, 5, 10, 20, 30, 45, 90];
  return candidates.find((candidate) => span / candidate <= 7) ?? 90;
}

function tickValues(minimum: number, maximum: number, step: number): number[] {
  const values = [];
  for (let value = Math.ceil(minimum / step) * step; value <= maximum + step * 1e-6; value += step) {
    values.push(Number(value.toFixed(8)));
  }
  return values;
}

function degreeLabel(value: number, positive: string, negative: string): string {
  const suffix = value > 0 ? positive : value < 0 ? negative : "";
  const magnitude = Number(Math.abs(value).toFixed(4));
  return `${magnitude}°${suffix}`;
}

function projectedMapTraces(
  group: ResultGroup,
  cells: SpatialCell[],
  grid: ProjectedGrid,
  coastlines: CoastlineCoordinates | null,
): Data[] {
  const longitudeExtent = numericExtent(cells.flatMap((cell) => cell.longitudes));
  const latitudeExtent = numericExtent(cells.flatMap((cell) => cell.latitudes));
  if (!longitudeExtent || !latitudeExtent) return [];
  const [west, east] = longitudeExtent;
  const [south, north] = latitudeExtent;
  const longitudeTicks = tickValues(west, east, niceInterval(east - west));
  const latitudeTicks = tickValues(south, north, niceInterval(north - south));
  const gridX: Array<number | null> = [];
  const gridY: Array<number | null> = [];
  const samples = 64;
  longitudeTicks.forEach((longitude) => {
    for (let index = 0; index <= samples; index += 1) {
      const latitude = south + ((north - south) * index) / samples;
      const projected = lambertProject(group, longitude, latitude);
      if (projected) { gridX.push(projected[0]); gridY.push(projected[1]); }
    }
    gridX.push(null); gridY.push(null);
  });
  latitudeTicks.forEach((latitude) => {
    for (let index = 0; index <= samples; index += 1) {
      const longitude = west + ((east - west) * index) / samples;
      const projected = lambertProject(group, longitude, latitude);
      if (projected) { gridX.push(projected[0]); gridY.push(projected[1]); }
    }
    gridX.push(null); gridY.push(null);
  });
  const traces: Data[] = [{
    type: "scatter", mode: "lines", x: gridX, y: gridY,
    line: { color: "rgba(112,132,147,0.48)", width: 0.8 },
    hoverinfo: "skip", showlegend: false,
  } as Data];

  const longitudeLabels = longitudeTicks.flatMap((longitude) => {
    const point = lambertProject(group, longitude, south + (north - south) * 0.025);
    return point ? [{ point, text: degreeLabel(longitude, "E", "W") }] : [];
  });
  const latitudeLabels = latitudeTicks.flatMap((latitude) => {
    const point = lambertProject(group, west + (east - west) * 0.025, latitude);
    return point ? [{ point, text: degreeLabel(latitude, "N", "S") }] : [];
  });
  traces.push({
    type: "scatter", mode: "text",
    x: longitudeLabels.map(({ point }) => point[0]),
    y: longitudeLabels.map(({ point }) => point[1]),
    text: longitudeLabels.map(({ text }) => text), textposition: "top center",
    textfont: { color: "#506878", size: 10 }, hoverinfo: "skip", showlegend: false,
  } as Data, {
    type: "scatter", mode: "text",
    x: latitudeLabels.map(({ point }) => point[0]),
    y: latitudeLabels.map(({ point }) => point[1]),
    text: latitudeLabels.map(({ text }) => text), textposition: "middle right",
    textfont: { color: "#506878", size: 10 }, hoverinfo: "skip", showlegend: false,
  } as Data);

  if (coastlines) {
    const coastlineX: Array<number | null> = [];
    const coastlineY: Array<number | null> = [];
    const xPadding = (grid.xRange[1] - grid.xRange[0]) * 0.08;
    const yPadding = (grid.yRange[1] - grid.yRange[0]) * 0.08;
    coastlines.longitudes.forEach((longitude, index) => {
      const latitude = coastlines.latitudes[index];
      if (longitude === null || latitude === null) {
        coastlineX.push(null); coastlineY.push(null); return;
      }
      const point = lambertProject(group, longitude, latitude);
      if (!point || point[0] < grid.xRange[0] - xPadding || point[0] > grid.xRange[1] + xPadding
          || point[1] < grid.yRange[0] - yPadding || point[1] > grid.yRange[1] + yPadding) {
        coastlineX.push(null); coastlineY.push(null); return;
      }
      coastlineX.push(point[0]); coastlineY.push(point[1]);
    });
    traces.push({
      type: "scatter", mode: "lines", x: coastlineX, y: coastlineY,
      line: { color: "#344e5c", width: 1.2 }, hoverinfo: "skip", showlegend: false,
    } as Data);
  }
  return traces;
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

function coordinateLabel(value: number, positive: string, negative: string): string {
  const suffix = value > 0 ? positive : value < 0 ? negative : "";
  return `${Number(Math.abs(value).toFixed(2))}°${suffix}`;
}

function plotMetadata(group: ResultGroup, query: QueryForm, catalog: Catalog): string {
  const resolution = spatialResolutionTitle(catalog, selectedDataset(group, catalog), group.coarseness_factor);
  const region = `${coordinateLabel(query.region.south, "N", "S")}–${coordinateLabel(query.region.north, "N", "S")}, ${coordinateLabel(query.region.west, "E", "W")}–${coordinateLabel(query.region.east, "E", "W")}`;
  return `${fallbackTitle(query.function)} · ${resolution} · ${query.time_unit} · ${query.time_start}–${query.time_end} · ${region}`;
}

function PinIcon({ filled = false }: { filled?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 3h6l-.8 5 3.3 3.3v1.4H13v7l-1 1.5-1-1.5v-7H6.5v-1.4L9.8 8 9 3Z" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

function PlotCardActions({ snapshot, pinned, onPin, onUnpin }: { snapshot: PlotSnapshot; pinned: boolean; onPin: (plot: PlotSnapshot) => void; onUnpin: (id: string) => void }) {
  return (
    <div className="plot-card-actions">
      {pinned && <span className="pinned-badge">Pinned</span>}
      <button className={pinned ? "icon-button active" : "icon-button"} type="button" title={pinned ? "Unpin plot" : "Pin plot for comparison"} aria-label={pinned ? "Unpin plot" : "Pin plot"} onClick={() => pinned ? onUnpin(snapshot.id) : onPin(snapshot)}><PinIcon filled={pinned} /></button>
      {pinned && <button className="icon-button remove" type="button" title="Remove pinned plot" aria-label="Remove pinned plot" onClick={() => onUnpin(snapshot.id)}>×</button>}
    </div>
  );
}

function SpatialPlot({ group, catalog, range, snapshot, pinned, onPin, onUnpin }: { group: ResultGroup; catalog: Catalog; range: ValueRange; snapshot: PlotSnapshot; pinned: boolean; onPin: (plot: PlotSnapshot) => void; onUnpin: (id: string) => void }) {
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
    const showPlotError = (error: unknown) => {
      if (disposed) return;
      console.error("Unable to render spatial plot", error);
      const message = error instanceof Error ? error.message : String(error);
      element.replaceChildren();
      const notice = document.createElement("p");
      notice.className = "plot-error";
      notice.textContent = `Unable to render this heatmap: ${message}`;
      element.append(notice);
    };
    let plot: AreaPlot;
    try {
      plot = areaPlot(group, catalog, range);
    } catch (error) {
      showPlotError(error);
      return;
    }
    const traces = plot.traces;
    const hasMatches = data.kind === "find-area" && data.matches?.some(Boolean);
    const layout: Partial<Layout> = {
      autosize: true,
      margin: { l: 58, r: 54, t: 8, b: hasMatches ? 76 : 54 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#f7fafc",
      font: { family: "Inter, ui-sans-serif, system-ui", color: "#17324d", size: 12 },
      showlegend: Boolean(hasMatches),
      legend: { orientation: "h", x: 0, y: -0.18, yanchor: "top" },
      xaxis: projected && plot.projectedGrid ? {
        title: { text: "Longitude" },
        showgrid: false,
        showticklabels: false,
        zeroline: false,
        showline: true,
        mirror: true,
        range: plot.projectedGrid.xRange,
      } : {
        title: { text: "Longitude" },
        gridcolor: "#b8c8d3",
        showline: true,
        mirror: true,
        ticks: "outside",
        range: paddedRange(longitudes),
      },
      yaxis: projected && plot.projectedGrid ? {
        title: { text: "Latitude" },
        showgrid: false,
        showticklabels: false,
        zeroline: false,
        showline: true,
        mirror: true,
        range: plot.projectedGrid.yRange,
        scaleanchor: "x",
        scaleratio: 1,
      } : {
        title: { text: "Latitude" },
        gridcolor: "#b8c8d3",
        showline: true,
        mirror: true,
        ticks: "outside",
        range: paddedRange(latitudes),
        scaleanchor: "x",
        scaleratio: 1,
      },
    };

    const coastlineRequest = loadCoastlines().catch(() => null);
    void Promise.all([import("plotly.js-dist-min"), coastlineRequest]).then(([{ default: Plotly }, coastlines]) => {
      if (disposed) return;
      plotly = Plotly;
      if (projected && plot.projectedGrid) {
        traces.splice(1, 0, ...projectedMapTraces(group, plot.cells, plot.projectedGrid, coastlines));
      } else if (coastlines) {
        traces.push(coastlineTrace(false, coastlines));
      }
      void Plotly.react(element, traces, layout, {
        responsive: true,
        displaylogo: false,
        topojsonURL: `${import.meta.env.BASE_URL}topojson/`,
      }).catch(showPlotError);
    });
    return () => {
      disposed = true;
      if (plotly) plotly.purge(element);
    };
  }, [catalog, group, projected, range.maximum, range.minimum]);

  return (
    <article className="spatial-plot-card">
      <header className="spatial-plot-heading">
        <div>
          <h3>{sourceName(group, catalog)}</h3>
          <p>{repositoryName(catalog, group.source.repository)} · {plotMetadata(group, snapshot.query, catalog)}</p>
        </div>
        <PlotCardActions snapshot={snapshot} pinned={pinned} onPin={onPin} onUnpin={onUnpin} />
      </header>
      <div className="spatial-plot" ref={plotRef} />
    </article>
  );
}

function TimePlot({ result, catalog, snapshot, pinned, onPin, onUnpin }: { result: QueryResult; catalog: Catalog; snapshot: PlotSnapshot; pinned: boolean; onPin: (plot: PlotSnapshot) => void; onUnpin: (id: string) => void }) {
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

  const datasets = result.groups.map((group) => sourceName(group, catalog)).join(" + ");
  return (
    <article className="spatial-plot-card time-plot-card">
      <header className="spatial-plot-heading">
        <div>
          <h3>{datasets}</h3>
          <p>{plotMetadata(result.groups[0], snapshot.query, catalog)}</p>
        </div>
        <PlotCardActions snapshot={snapshot} pinned={pinned} onPin={onPin} onUnpin={onUnpin} />
      </header>
      <div className="spatial-plot" ref={plotRef} />
    </article>
  );
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

function snapshotsForResult(result: QueryResult, query: QueryForm): PlotSnapshot[] {
  const areaGroups = result.groups.filter(isAreaGroup);
  if (areaGroups.length) {
    return areaGroups.map((group) => ({
      id: `${result.query_id}:${group.group_id}`,
      result: { ...result, groups: [group] },
      query,
      colorRange: valueRange(areaGroups, group),
    }));
  }
  if (result.function === "timeseries" || result.function === "find-time") {
    return [{ id: `${result.query_id}:time`, result, query }];
  }
  return [];
}

export default function PlotPanel({ result, query, loading, catalog, pinnedPlots, layout, useSharedScale, onPin, onUnpin }: Props) {
  const currentPlots = result && query ? snapshotsForResult(result, query) : [];
  const currentIds = new Set(currentPlots.map((plot) => plot.id));
  const plots = [...pinnedPlots.filter((plot) => !currentIds.has(plot.id)), ...currentPlots];

  if (!plots.length && loading) return <section className="result-panel state-panel"><div className="spinner" /><h2>Reading Polar-is storage</h2><p>The query may take a moment for a large region or fine resolution.</p></section>;
  if (!plots.length && !result) return <section className="result-panel state-panel"><div className="empty-orbit" aria-hidden="true" /><h2>No result yet</h2><p>Select a region and data object, then run a query.</p></section>;
  if (!plots.length && result && !result.groups.length) return <section className="result-panel state-panel"><h2>No matching data</h2><p>Try another region, time interval, or resolution. Review the warnings below for details.</p></section>;
  if (!plots.length && result?.function === "get-data") return <section className="result-panel state-panel"><h2>Data is ready</h2><p>The query returned {result.groups.reduce((sum, group) => sum + (group.data.kind === "get-data" ? group.data.cell_count : 0), 0).toLocaleString()} spatial cells. Use the download links below to save the NetCDF results.</p></section>;

  const sharedGroups = plots.flatMap((plot) => plot.result.groups.filter(isAreaGroup));
  return (
    <section className="result-panel spatial-result-panel">
      {loading && <div className="plot-loading-banner"><span className="spinner" /> Running the next query…</div>}
      <div className={`spatial-plot-grid ${layout}`}>
        {plots.map((snapshot) => {
          const pinned = pinnedPlots.some((plot) => plot.id === snapshot.id);
          const areaGroup = snapshot.result.groups.find(isAreaGroup);
          if (areaGroup) {
            const range = useSharedScale
              ? valueRange(sharedGroups, areaGroup)
              : snapshot.colorRange ?? valueRange(snapshot.result.groups, areaGroup);
            return <SpatialPlot key={snapshot.id} group={areaGroup} catalog={catalog} range={range} snapshot={snapshot} pinned={pinned} onPin={onPin} onUnpin={onUnpin} />;
          }
          return <TimePlot key={snapshot.id} result={snapshot.result} catalog={catalog} snapshot={snapshot} pinned={pinned} onPin={onPin} onUnpin={onUnpin} />;
        })}
      </div>
    </section>
  );
}
