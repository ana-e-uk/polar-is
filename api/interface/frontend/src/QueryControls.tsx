import type { Catalog, Dataset, QueryForm, Region } from "./types";

type Props = {
  catalog: Catalog;
  form: QueryForm;
  onChange: (form: QueryForm) => void;
  onSubmit: () => void;
  onShowAvailability: () => void;
  loading: boolean;
};

const label = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ").replace(/\b\w/g, (c) => c.toUpperCase());

export default function QueryControls({ catalog, form, onChange, onSubmit, onShowAvailability, loading }: Props) {
  const repositories = catalog.repositories.filter((item) => item.datasets.length > 0);
  const availableDatasets = form.repository
    ? repositories.find((item) => item.name === form.repository)?.datasets ?? []
    : repositories.flatMap((item) => item.datasets);
  const datasets = Array.from(new Map(availableDatasets.map((item) => [item.name, item])).values());
  const selectedDataset = datasets.find((item) => item.name === form.dataset);
  const variables = Array.from(
    new Set((selectedDataset ? [selectedDataset] : datasets).flatMap((item) => item.variables)),
  ).sort();

  function changeRepository(repository: string) {
    const nextDatasets = repository
      ? repositories.find((item) => item.name === repository)?.datasets ?? []
      : repositories.flatMap((item) => item.datasets);
    const dataset = form.dataset && nextDatasets.some((item) => item.name === form.dataset)
      ? form.dataset
      : "";
    const scoped = dataset ? nextDatasets.filter((item) => item.name === dataset) : nextDatasets;
    const scopedVariables = Array.from(new Set(scoped.flatMap((item) => item.variables))).sort();
    onChange({ ...form, repository, dataset, variable: scopedVariables[0] ?? "", additional_parameters: {} });
  }

  function changeDataset(datasetName: string) {
    const dataset = datasets.find((item) => item.name === datasetName);
    const nextParameters: Record<string, string | number> = {};
    Object.entries(dataset?.additional_parameters ?? {}).forEach(([name, options]) => {
      if (options.length) nextParameters[name] = options[0];
    });
    onChange({
      ...form,
      dataset: datasetName,
      variable: dataset?.variables[0] ?? variables[0] ?? "",
      additional_parameters: nextParameters,
    });
  }

  function changeRegion(name: keyof Region, value: string) {
    onChange({ ...form, region: { ...form.region, [name]: Number(value) } });
  }

  return (
    <section className="controls-panel">
      <div className="panel-heading compact">
        <div>
          <p className="eyebrow">Data object</p>
          <h2>Query parameters</h2>
        </div>
      </div>
      <div className="control-grid">
        <label>Repository<select value={form.repository} onChange={(e) => changeRepository(e.target.value)}><option value="">Any</option>{repositories.map((item) => <option key={item.name} value={item.name}>{label(item.name)}</option>)}</select></label>
        <label>Dataset<select value={form.dataset} onChange={(e) => changeDataset(e.target.value)}><option value="">Any</option>{datasets.map((item) => <option key={item.name} value={item.name}>{label(item.name)}</option>)}</select></label>
        <label>Variable<select required value={form.variable} onChange={(e) => onChange({ ...form, variable: e.target.value })}><option value="">Select variable</option>{variables.map((item) => <option key={item} value={item}>{label(item)}</option>)}</select></label>
        {selectedDataset && <AdditionalParameters dataset={selectedDataset} form={form} onChange={onChange} />}
        <label>Start<input type="date" required value={form.time_start} onChange={(e) => onChange({ ...form, time_start: e.target.value })} /></label>
        <label>End<input type="date" required value={form.time_end} onChange={(e) => onChange({ ...form, time_end: e.target.value })} /></label>
        <label>Spatial resolution<select value={form.coarseness_factor} onChange={(e) => onChange({ ...form, coarseness_factor: Number(e.target.value) })}>{catalog.coarseness_factors.map((item) => <option key={item} value={item}>{item === 1 ? "Source" : `Coarsen-${item}`}</option>)}</select></label>
        <label>Time resolution<select value={form.time_unit} onChange={(e) => onChange({ ...form, time_unit: e.target.value })}>{catalog.time_units.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label>Function<select value={form.function} onChange={(e) => onChange({ ...form, function: e.target.value })}>{catalog.functions.map((item) => <option key={item} value={item}>{label(item)}</option>)}</select></label>
        <label>Aggregation<select value={form.aggregation_method} onChange={(e) => onChange({ ...form, aggregation_method: e.target.value })}>{catalog.aggregation_methods.map((item) => <option key={item} value={item}>{label(item)}</option>)}</select></label>
        {(form.function === "find-time" || form.function === "find-area") && <>
          <label>Predicate<select value={form.predicate} onChange={(e) => onChange({ ...form, predicate: e.target.value })}><option value="gt">Greater than (&gt;)</option><option value="ge">Greater than or equal (≥)</option><option value="lt">Less than (&lt;)</option><option value="le">Less than or equal (≤)</option><option value="eq">Equal (=)</option><option value="ne">Not equal (≠)</option></select></label>
          <label>Filter value<input type="number" required step="any" value={form.filter_value} onChange={(e) => onChange({ ...form, filter_value: e.target.value })} placeholder="Enter a value" /></label>
        </>}
      </div>
      <fieldset className="bounds-grid">
        <legend>Region bounds</legend>
        {(["north", "south", "west", "east"] as const).map((name) => (
          <label key={name}>{label(name)}<input type="number" min={name === "north" || name === "south" ? -90 : -180} max={name === "north" || name === "south" ? 90 : 180} step="0.001" value={form.region[name]} onChange={(e) => changeRegion(name, e.target.value)} /></label>
        ))}
      </fieldset>
      <div className="control-actions">
        <button className="availability-button" type="button" onClick={onShowAvailability}>Available data</button>
        <button className="query-button" type="button" onClick={onSubmit} disabled={loading || !form.variable}>
          {loading ? "Running query…" : "Run query"}
        </button>
      </div>
    </section>
  );
}

function AdditionalParameters({ dataset, form, onChange }: { dataset: Dataset; form: QueryForm; onChange: (form: QueryForm) => void }) {
  return <>{Object.entries(dataset.additional_parameters).map(([name, options]) => (
    <label key={name}>{label(name)}<select value={String(form.additional_parameters[name] ?? "")} onChange={(e) => onChange({ ...form, additional_parameters: { ...form.additional_parameters, [name]: e.target.value } })}>{options.map((item) => <option key={String(item)} value={String(item)}>{label(String(item))}</option>)}</select></label>
  ))}</>;
}
