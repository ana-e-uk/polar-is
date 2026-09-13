import { useEffect, useRef } from "react";
import type { Data, Layout } from "plotly.js";
import type { QueryResult, ResultGroup } from "./types";

type Props = { result: QueryResult | null; loading: boolean };

const sourceName = (group: ResultGroup) => {
  const details = Object.values(group.source.additional_parameters).join(", ");
  return `${group.source.dataset}${details ? ` · ${details}` : ""}`;
};

export default function PlotPanel({ result, loading }: Props) {
  const plotRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!plotRef.current || !result?.groups.length) return;
    let disposed = false;
    let plotly: typeof import("plotly.js-dist-min").default | null = null;
    const element = plotRef.current;
    const groups = result.groups;
    const traces: Data[] = groups.flatMap((group) => {
      const data = group.data;
      if (data.kind === "timeseries" || data.kind === "find-time") {
        return [{ type: "scatter", mode: "lines+markers", x: data.timestamps, y: data.values, name: sourceName(group), line: { width: 2 } } as Data];
      }
      if (data.kind === "heatmap" || data.kind === "find-area") {
        return [{ type: "scattergeo", mode: "markers", lat: data.latitudes, lon: data.longitudes, name: sourceName(group), marker: { size: 9, color: data.values, colorscale: "Viridis", colorbar: { title: { text: group.units ?? "Value" } } } } as Data];
      }
      return [];
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
      geo: isArea ? { projection: { type: "equirectangular" }, showland: true, landcolor: "#e7eef2", showcountries: true, countrycolor: "#c3d0da", fitbounds: "locations" } : undefined,
    };
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
