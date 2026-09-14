import { useEffect, useRef } from "react";
import type { Data, Layout } from "plotly.js";
import type { QueryResult, ResultGroup } from "./types";

type Props = { result: QueryResult | null; loading: boolean };

const sourceName = (group: ResultGroup) => {
  const details = Object.values(group.source.additional_parameters).join(", ");
  return `${group.source.dataset}${details ? ` · ${details}` : ""}`;
};

function areaTrace(group: ResultGroup): Data[] {
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
      feature: {
        type: "Feature",
        properties: { id },
        geometry: {
          type: "Polygon",
          coordinates: [[
            ...(longitudes as number[]).map((item, corner) => [item, (latitudes as number[])[corner]]),
            [(longitudes as number[])[0], (latitudes as number[])[0]],
          ]],
        },
      },
    }];
  });
  if (!cells.length) return [];
  const traces: Data[] = [{
    type: "choropleth",
    name: sourceName(group),
    geojson: { type: "FeatureCollection", features: cells.map((cell) => cell.feature) },
    featureidkey: "properties.id",
    locations: cells.map((cell) => cell.id),
    z: cells.map((cell) => cell.value),
    text: cells.map((cell) => cell.label),
    hovertemplate: `%{text}<br>%{z} ${group.units ?? ""}<extra>${sourceName(group)}</extra>`,
    coloraxis: "coloraxis",
    showscale: false,
    marker: { line: { width: 0.25, color: "rgba(255,255,255,.35)" } },
  } as Data];
  const matches = cells.filter((cell) => cell.matches);
  if (data.kind === "find-area" && matches.length) {
    const lat: Array<number | null> = [];
    const lon: Array<number | null> = [];
    matches.forEach((cell) => {
      lat.push(...cell.latitudes, cell.latitudes[0], null);
      lon.push(...cell.longitudes, cell.longitudes[0], null);
    });
    traces.push({
      type: "scattergeo",
      mode: "lines",
      lat,
      lon,
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
      return areaTrace(group);
    });
    const isArea = groups[0].data.kind === "heatmap" || groups[0].data.kind === "find-area";
    const layout: Partial<Layout> = {
      autosize: true,
      margin: { l: 56, r: 28, t: 22, b: 52 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#f7fafc",
      font: { family: "Inter, ui-sans-serif, system-ui", color: "#17324d", size: 13 },
      legend: { orientation: "h", y: -0.2 },
      xaxis: { title: { text: "Time" }, gridcolor: "#dbe6ef" },
      yaxis: { title: { text: groups[0].units ?? "Value" }, gridcolor: "#dbe6ef" },
      geo: isArea ? {
        projection: { type: "equirectangular" },
        showland: true,
        landcolor: "#e7eef2",
        showocean: true,
        oceancolor: "#f3f8fa",
        showcoastlines: true,
        coastlinecolor: "#506878",
        showcountries: true,
        countrycolor: "#8194a1",
        fitbounds: "locations",
        lonaxis: { showgrid: true, gridcolor: "#b8c8d3", dtick: 10 },
        lataxis: { showgrid: true, gridcolor: "#b8c8d3", dtick: 10 },
      } : undefined,
    };
    if (isArea) {
      (layout as Partial<Layout> & { coloraxis: object }).coloraxis = {
        colorscale: "Viridis",
        cmin: zmin,
        cmax: zmax === zmin ? zmin + 1 : zmax,
        colorbar: { title: { text: groups[0].units ?? "Value" } },
      };
    }
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
    void import("plotly.js-dist-min").then(({ default: Plotly }) => {
      if (disposed) return;
      plotly = Plotly;
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
