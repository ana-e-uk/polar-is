import { useEffect, useMemo, useState } from "react";
import { fetchAvailability, fetchCatalog, runQuery } from "./api";
import AvailabilityTable from "./AvailabilityTable";
import PlotPanel from "./PlotPanel";
import QueryControls from "./QueryControls";
import RegionPicker from "./RegionPicker";
import type { AvailabilityRow, Catalog, PlotLayout, PlotSnapshot, QueryForm, QueryResult } from "./types";
import { datasetName, variableTitle } from "./titles";

const initialForm: QueryForm = {
  repository: "",
  dataset: "",
  variable: "",
  time_start: "2018-01-01",
  time_end: "2018-01-31",
  region: { west: -20, east: 90, south: 55, north: 90 },
  coarseness_factor: 4,
  time_unit: "Day",
  function: "timeseries",
  aggregation_method: "mean",
  additional_parameters: {},
  predicate: "gt",
  filter_value: "",
};

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [form, setForm] = useState<QueryForm>(initialForm);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [resultQuery, setResultQuery] = useState<QueryForm | null>(null);
  const [pinnedPlots, setPinnedPlots] = useState<PlotSnapshot[]>([]);
  const [plotLayout, setPlotLayout] = useState<PlotLayout>("grid");
  const [useSharedScale, setUseSharedScale] = useState(false);
  const [pinNotice, setPinNotice] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [jobStatus, setJobStatus] = useState("");
  const [error, setError] = useState("");
  const [showMap, setShowMap] = useState(true);
  const [showAvailability, setShowAvailability] = useState(false);
  const [availability, setAvailability] = useState<AvailabilityRow[]>([]);
  const [availabilityLoading, setAvailabilityLoading] = useState(false);
  const [availabilityError, setAvailabilityError] = useState("");

  useEffect(() => {
    fetchCatalog().then((next) => {
      setCatalog(next);
      const repositories = next.repositories.filter((item) => item.datasets.length);
      const variables = Array.from(new Set(repositories.flatMap((repo) => repo.datasets.flatMap((dataset) => dataset.variables)))).sort();
      setForm((current) => ({ ...current, variable: variables[0] ?? "", coarseness_factor: next.coarseness_factors.includes(4) ? 4 : next.coarseness_factors.at(-1) ?? 1 }));
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  const warnings = useMemo(() => {
    if (!result) return [];
    return Array.from(new Set([...result.warnings, ...result.groups.flatMap((group) => group.warnings)]));
  }, [result]);
  const displayedVariable = catalog && form.variable
    ? variableTitle(catalog, form.variable)
    : "Choose a variable";

  async function submit() {
    setError("");
    if (!form.variable || !form.time_start || !form.time_end) {
      setError("Choose a variable and enter both dates before running the query.");
      return;
    }
    if (form.region.west >= form.region.east || form.region.south >= form.region.north) {
      setError("Enter a region where West is less than East and South is less than North.");
      return;
    }
    if ((form.function === "find-time" || form.function === "find-area") && form.filter_value === "") {
      setError("Enter a filter value for the selected find function.");
      return;
    }
    setLoading(true);
    setJobStatus("Submitting your query…");
    const submittedForm: QueryForm = {
      ...form,
      region: { ...form.region },
      additional_parameters: { ...form.additional_parameters },
    };
    try {
      const next = await runQuery(submittedForm, setJobStatus);
      setResult(next);
      setResultQuery(submittedForm);
      setShowMap(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The query could not be completed.");
    } finally {
      setLoading(false);
      setJobStatus("");
    }
  }

  function pinPlot(plot: PlotSnapshot) {
    setPinNotice("");
    if (pinnedPlots.some((item) => item.id === plot.id)) return;
    if (pinnedPlots.length >= 2) {
      setPinNotice("Two plots are already pinned. Remove one before pinning another.");
      return;
    }
    setPinnedPlots((current) => [...current, plot]);
  }

  function unpinPlot(id: string) {
    setPinNotice("");
    setPinnedPlots((current) => current.filter((item) => item.id !== id));
  }

  async function openAvailability() {
    setShowAvailability(true);
    if (availability.length) return;
    setAvailabilityLoading(true);
    setAvailabilityError("");
    try {
      setAvailability(await fetchAvailability());
    } catch (reason) {
      setAvailabilityError(reason instanceof Error ? reason.message : "Available data could not be loaded.");
    } finally {
      setAvailabilityLoading(false);
    }
  }

  return (
    <main>
      <header className="app-header">
        <div className="brand-mark" aria-hidden="true"><span /></div>
        <div><p className="eyebrow">Polar-is</p><h1>Data Explorer</h1></div>
        <div className="header-note">Spatio-temporal environmental data</div>
      </header>
      {error && <div className="message error" role="alert"><strong>Query could not run.</strong> {error}</div>}
      {loading && <div className="message" role="status" aria-live="polite">{jobStatus}</div>}
      <div className={sidebarCollapsed ? "workspace sidebar-collapsed" : "workspace"}>
        <div className="primary-column">
          {showMap ? <RegionPicker region={form.region} onChange={(region) => setForm({ ...form, region })} /> : (
            <div className="result-wrap">
              <div className="result-heading">
                <div><p className="eyebrow">Query result</p><h2>{displayedVariable}</h2></div>
                <button className="secondary-button" type="button" onClick={() => setShowMap(true)}>Change region</button>
              </div>
              {catalog && <PlotPanel result={result} query={resultQuery} loading={loading} catalog={catalog} pinnedPlots={pinnedPlots} layout={plotLayout} useSharedScale={useSharedScale} onPin={pinPlot} onUnpin={unpinPlot} />}
            </div>
          )}
        </div>
        {!sidebarCollapsed && <aside className="side-column">
          {catalog ? <QueryControls catalog={catalog} form={form} onChange={setForm} onSubmit={submit} onShowAvailability={openAvailability} onCollapse={() => setSidebarCollapsed(true)} loading={loading} /> : <section className="controls-panel state-panel"><div className="spinner" /><p>Loading available data…</p></section>}
          <section className="plot-controls-card">
            <p className="eyebrow">Plot controls</p>
            <div className="plot-control-row">
              <div className="view-toggle" role="group" aria-label="Plot layout">
                {(["grid", "large"] as PlotLayout[]).map((mode) => (
                  <button key={mode} type="button" className={plotLayout === mode ? "active" : ""} onClick={() => setPlotLayout(mode)}>{mode === "grid" ? "Grid" : "Large"}</button>
                ))}
              </div>
              <label className="shared-scale" title="Use one color range for visible plots that have matching units">
                <input type="checkbox" checked={useSharedScale} onChange={(event) => setUseSharedScale(event.target.checked)} />
                Use shared scale
              </label>
            </div>
            {pinnedPlots.length > 0 && <button className="text-button clear-pinned-button" type="button" onClick={() => { setPinnedPlots([]); setPinNotice(""); }}>Clear pinned</button>}
            {pinNotice && <span className="pin-notice" role="status">{pinNotice}</span>}
          </section>
          {result?.groups.length ? <section className="downloads-section">
            <p className="eyebrow">Downloads</p>
            {result.groups.map((group) => <section className="download-card" key={group.group_id}><div><strong>{catalog ? datasetName(catalog, group.source.repository, group.source.dataset) : group.source.dataset}</strong><span>{group.coverage.hit_count.toLocaleString()} covered cells</span></div><a href={group.download_url}>NetCDF</a></section>)}
          </section> : null}
          {warnings.length > 0 && <section className="warnings" aria-live="polite"><h2>Coverage notes</h2><ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></section>}
        </aside>}
        {sidebarCollapsed && <button className="sidebar-reopen-button" type="button" onClick={() => setSidebarCollapsed(false)} title="Open data and plot controls" aria-label="Open data and plot controls">‹</button>}
      </div>
      {showAvailability && catalog && <AvailabilityTable rows={availability} loading={availabilityLoading} error={availabilityError} catalog={catalog} onClose={() => setShowAvailability(false)} />}
    </main>
  );
}
