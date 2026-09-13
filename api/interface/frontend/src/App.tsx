import { useEffect, useMemo, useState } from "react";
import { fetchCatalog, runQuery } from "./api";
import PlotPanel from "./PlotPanel";
import QueryControls from "./QueryControls";
import RegionPicker from "./RegionPicker";
import type { Catalog, QueryForm, QueryResult } from "./types";

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
};

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [form, setForm] = useState<QueryForm>(initialForm);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showMap, setShowMap] = useState(true);

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

  async function submit() {
    setLoading(true);
    setError("");
    try {
      const next = await runQuery(form);
      setResult(next);
      setShowMap(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The query could not be completed.");
    } finally {
      setLoading(false);
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
      <div className="workspace">
        <div className="primary-column">
          {showMap ? <RegionPicker region={form.region} onChange={(region) => setForm({ ...form, region })} /> : (
            <div className="result-wrap">
              <div className="result-heading"><div><p className="eyebrow">Query result</p><h2>{form.variable.replaceAll("_", " ")}</h2></div><button className="secondary-button" onClick={() => setShowMap(true)}>Change region</button></div>
              <PlotPanel result={result} loading={loading} />
            </div>
          )}
        </div>
        <aside className="side-column">
          <section className="summary-card"><p className="eyebrow">Current selection</p><h2>{form.variable ? form.variable.replaceAll("_", " ") : "Choose a variable"}</h2><dl><div><dt>Function</dt><dd>{form.function}</dd></div><div><dt>Resolution</dt><dd>{form.coarseness_factor === 1 ? "Source" : `Coarsen-${form.coarseness_factor}`} · {form.time_unit}</dd></div><div><dt>Dates</dt><dd>{form.time_start} — {form.time_end}</dd></div></dl></section>
          {result?.groups.map((group) => <section className="download-card" key={group.group_id}><div><strong>{group.source.dataset}</strong><span>{group.coverage.hit_count.toLocaleString()} covered cells</span></div><a href={group.download_url}>Download NetCDF</a></section>)}
          {warnings.length > 0 && <section className="warnings" aria-live="polite"><h2>Coverage notes</h2><ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></section>}
        </aside>
        <div className="controls-row">
          {catalog ? <QueryControls catalog={catalog} form={form} onChange={setForm} onSubmit={submit} loading={loading} /> : <section className="controls-panel state-panel"><div className="spinner" /><p>Loading available data…</p></section>}
        </div>
      </div>
    </main>
  );
}

