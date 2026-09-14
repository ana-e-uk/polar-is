import { useEffect, useRef } from "react";
import type { Data, Layout } from "plotly.js";
import { loadCoastlines } from "./geoTopology";
import type { QueryResult, ResultGroup } from "./types";

type Props = { result: QueryResult | null; loading: boolean };

const sourceName = (group: ResultGroup) => {
  const details = Object.values(group.source.additional_parameters).join(", ");
  return `${group.source.dataset}${details ? ` · ${details}` : ""}`;
};

const VIRIDIS = [
  "#440154",
  "#482878",
  "#3e4989",
  "#31688e",
  "#26828e",
  "#1f9e89",
  "#35b779",
  "#6ece58",
  "#b5de2b",
  "#fde725",
];

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

function areaTrace(
  group: ResultGroup,
  showScale: boolean,
  zmin: number,
  zmax: number,
): Data[] {
  const data = group.data;
  if (data.kind !== "heatmap" && data.kind !== "find-area") return [];
  const cells = data.values.flatMap((value, index) => {
    const latitude = data.latitudes[index];
    const longitude = data.longitudes[index];
    const latitudes = data.corner_latitudes[index];
    const longitudes = data.corner_longitudes[index];
    if (value === null || latitude === null || longitude === null ||
        latitudes?.some((item) => item === null) || longitudes?.some((item) => item === null)) return [];
    const id = data.cell_ids[index];
    return [{
      id,
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

  // Matplotlib's working notebook uses a PolyCollection whose face color is
  // calculated from each value. Do the same here instead of relying on
  // Plotly's GeoJSON location-to-z join, which can render every feature with
  // one color even though its hover z values differ.
  const traces: Data[] = cells.map((cell) => {
    const color = viridisColor(cell.value, zmin, zmax);
    return {
      type: "scatter",
      mode: "lines",
      x: [...cell.longitudes, cell.longitudes[0]],
      y: [...cell.latitudes, cell.latitudes[0]],
      fill: "toself",
      fillcolor: color,
      connectgaps: false,
      line: { color: "rgba(255,255,255,0.25)", width: 0.25 },
      hoverinfo: "skip",
      showlegend: false,
    } as Data;
  });

  // Invisible center markers preserve exact per-cell hover labels and values.
  traces.push({
    type: "scatter",
    mode: "markers",
    x: cells.map((cell) => cell.longitude),
    y: cells.map((cell) => cell.latitude),
    text: cells.map((cell) => cell.label),
    customdata: cells.map((cell) => cell.value),
    name: sourceName(group),
    marker: { size: 12, color: "rgba(255,255,255,0.001)" },
    hovertemplate: `%{text}<br>%{customdata} ${group.units ?? ""}<extra>${sourceName(group)}</extra>`,
    showlegend: false,
  } as Data);

  // A zero-size numeric marker supplies the continuous colorbar for the
  // directly colored polygon bins.
  traces.push({
    type: "scatter",
    mode: "markers",
    x: [cells[0].longitude, cells[0].longitude],
    y: [cells[0].latitude, cells[0].latitude],
    marker: {
      size: 0,
      opacity: 0,
      color: [zmin, zmax],
      autocolorscale: false,
      colorscale: "Viridis",
      cmin: zmin,
      cmax: zmax === zmin ? zmin + 1 : zmax,
      showscale: showScale,
      colorbar: { title: { text: group.units ?? "Value" } },
    },
    hoverinfo: "skip",
    showlegend: false,
  } as Data);
  const matches = cells.filter((cell) => cell.matches);
  if (data.kind === "find-area" && matches.length) {
    const latitudes: Array<number | null> = [];
    const longitudes: Array<number | null> = [];
    matches.forEach((cell) => {
      latitudes.push(...cell.latitudes, cell.latitudes[0], null);
      longitudes.push(...cell.longitudes, cell.longitudes[0], null);
    });
    traces.push({
      type: "scatter",
      mode: "lines",
      x: longitudes,
      y: latitudes,
      name: "Matches filter",
      hoverinfo: "skip",
      line: { color: "#dc2626", width: 2.5 },
    } as Data);
  }
  return traces;
}

export default function PlotPanel({ result, loading }: Props) {
  const plotRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!plotRef.current || !result?.groups.length) return;
    let disposed = false;
    let plotly: typeof import("plotly.js-dist-min").default | null = null;
    const element = plotRef.current;
    const groups = result.groups;
    const areaValues = groups.flatMap((group) => {
      const data = group.data;
      if (data.kind !== "heatmap" && data.kind !== "find-area") return [];
      return data.values.filter((value): value is number => value !== null);
    });
    const [zmin, zmax] = areaValues.reduce<[number, number]>(
      ([minimum, maximum], value) => [Math.min(minimum, value), Math.max(maximum, value)],
      areaValues.length ? [areaValues[0], areaValues[0]] : [0, 1],
    );
    const areaLongitudes = groups.flatMap((group) => {
      const data = group.data;
      if (data.kind !== "heatmap" && data.kind !== "find-area") return [];
      return data.corner_longitudes.flat().filter((value): value is number => value !== null);
    });
    const areaLatitudes = groups.flatMap((group) => {
      const data = group.data;
      if (data.kind !== "heatmap" && data.kind !== "find-area") return [];
      return data.corner_latitudes.flat().filter((value): value is number => value !== null);
    });
    let areaGroupIndex = 0;
    const traces: Data[] = groups.flatMap((group) => {
      const data = group.data;
      if (data.kind === "timeseries" || data.kind === "find-time") {
        const timeTraces: Data[] = [{ type: "scatter", mode: "lines+markers", x: data.timestamps, y: data.values, name: sourceName(group), line: { width: 2 }, marker: { size: 5 } } as Data];
        if (data.kind === "find-time" && data.matches) {
          timeTraces.push({
            type: "scatter",
            mode: "markers",
            x: data.timestamps.filter((_, index) => data.matches?.[index]),
            y: data.values.filter((_, index) => data.matches?.[index]),
            name: "Matches filter",
            marker: { color: "#dc2626", size: 10, line: { color: "white", width: 1 } },
          } as Data);
        }
        return timeTraces;
      }
      const groupTraces = areaTrace(group, areaGroupIndex === 0, zmin, zmax);
      areaGroupIndex += 1;
      return groupTraces;
    });
    const isArea = groups[0].data.kind === "heatmap" || groups[0].data.kind === "find-area";
    const layout: Partial<Layout> = {
      autosize: true,
      margin: { l: 56, r: 28, t: 22, b: 52 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#f7fafc",
      font: { family: "Inter, ui-sans-serif, system-ui", color: "#17324d", size: 13 },
      legend: { orientation: "h", y: -0.2 },
      xaxis: isArea ? {
        title: { text: "Longitude" },
        gridcolor: "#b8c8d3",
        showline: true,
        mirror: true,
        ticks: "outside",
        range: areaLongitudes.length ? [Math.min(...areaLongitudes), Math.max(...areaLongitudes)] : undefined,
      } : { title: { text: "Time" }, gridcolor: "#dbe6ef" },
      yaxis: isArea ? {
        title: { text: "Latitude" },
        gridcolor: "#b8c8d3",
        showline: true,
        mirror: true,
        ticks: "outside",
        range: areaLatitudes.length ? [Math.min(...areaLatitudes), Math.max(...areaLatitudes)] : undefined,
      } : { title: { text: groups[0].units ?? "Value" }, gridcolor: "#dbe6ef" },
    };
    if (!isArea && groups[0].data.kind === "find-time" && groups[0].data.filter_value !== undefined) {
      layout.shapes = [{
        type: "line",
        xref: "paper",
        x0: 0,
        x1: 1,
        y0: groups[0].data.filter_value,
        y1: groups[0].data.filter_value,
        line: { color: "#dc2626", width: 1.5, dash: "dash" },
      }];
    }
    const coastlineRequest = isArea ? loadCoastlines() : Promise.resolve(null);
    void Promise.all([import("plotly.js-dist-min"), coastlineRequest]).then(([{ default: Plotly }, coastlines]) => {
      if (disposed) return;
      plotly = Plotly;
      if (coastlines) {
        traces.push({
          type: "scatter",
          mode: "lines",
          x: coastlines.longitudes,
          y: coastlines.latitudes,
          line: { color: "#344e5c", width: 1.2 },
          hoverinfo: "skip",
          showlegend: false,
        } as Data);
      }
      Plotly.react(element, traces, layout, { responsive: true, displaylogo: false });
    });
    return () => {
      disposed = true;
      if (plotly) plotly.purge(element);
    };
  }, [result]);

  if (loading) return <section className="result-panel state-panel"><div className="spinner" /><h2>Reading Polar-is storage</h2><p>The query may take a moment for a large region or fine resolution.</p></section>;
  if (!result) return <section className="result-panel state-panel"><div className="empty-orbit" aria-hidden="true" /><h2>No result yet</h2><p>Select a region and data object, then run a query.</p></section>;
  if (!result.groups.length) return <section className="result-panel state-panel"><h2>No matching data</h2><p>Try another region, time interval, or resolution. Review the warnings below for details.</p></section>;
  if (result.function === "get-data") return <section className="result-panel state-panel"><h2>Data is ready</h2><p>The query returned {result.groups.reduce((sum, group) => sum + (group.data.kind === "get-data" ? group.data.cell_count : 0), 0).toLocaleString()} spatial cells. Use the download links below to save the NetCDF results.</p></section>;
  return <section className="result-panel"><div className="plot" ref={plotRef} /></section>;
}
