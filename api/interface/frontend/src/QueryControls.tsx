import type { Catalog, Dataset, QueryForm, Region } from "./types";
import { fallbackTitle, repositoryTitle, spatialResolutionTitle, variableTitle } from "./titles";

type Props = {
  catalog: Catalog;
  form: QueryForm;
  onChange: (form: QueryForm) => void;
  onSubmit: () => void;
  onShowAvailability: () => void;
  onCollapse: () => void;
  loading: boolean;
};

export default function QueryControls({ catalog, form, onChange, onSubmit, onShowAvailability, onCollapse, loading }: Props) {
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
    <section className="controls-panel data-object-card">
      <div className="controls-card-heading">
        <p className="eyebrow">Data object</p>
        <button className="icon-button sidebar-collapse-button" type="button" onClick={onCollapse} title="Collapse sidebar" aria-label="Collapse sidebar">›</button>
      </div>
      <button className="query-button sidebar-run-button" type="button" onClick={onSubmit} disabled={loading || !form.variable}>
        {loading ? "Running query…" : "Run query"}
      </button>
      <div className="controls-body">
        <div className="sidebar-control-grid">
          <div className="control-button-field"><span>Catalog</span><button className="availability-button" type="button" onClick={onShowAvailability}>Available data</button></div>
          <label>Repository<select value={form.repository} onChange={(e) => changeRepository(e.target.value)}><option value="">Any</option>{repositories.map((item) => <option key={item.name} value={item.name}>{repositoryTitle(item)}</option>)}</select></label>
          <label>Dataset<select value={form.dataset} onChange={(e) => changeDataset(e.target.value)}><option value="">Any</option>{datasets.map((item) => <option key={item.name} value={item.name}>{item.display_name ?? fallbackTitle(item.name)}</option>)}</select></label>
          <label>Variable<select required value={form.variable} onChange={(e) => onChange({ ...form, variable: e.target.value })}><option value="">Select variable</option>{variables.map((item) => <option key={item} value={item}>{variableTitle(catalog, item)}</option>)}</select></label>
          {selectedDataset && <AdditionalParameters dataset={selectedDataset} form={form} onChange={onChange} />}
          <label>Start<input type="date" required value={form.time_start} onChange={(e) => onChange({ ...form, time_start: e.target.value })} /></label>
          <label>End<input type="date" required value={form.time_end} onChange={(e) => onChange({ ...form, time_end: e.target.value })} /></label>
          {(form.function === "find-time" || form.function === "find-area") && <>
            <label>Predicate<select value={form.predicate} onChange={(e) => onChange({ ...form, predicate: e.target.value })}><option value="gt">Greater than (&gt;)</option><option value="ge">Greater than or equal (≥)</option><option value="lt">Less than (&lt;)</option><option value="le">Less than or equal (≤)</option><option value="eq">Equal (=)</option><option value="ne">Not equal (≠)</option></select></label>
            <label>Filter value<input type="number" required step="any" value={form.filter_value} onChange={(e) => onChange({ ...form, filter_value: e.target.value })} placeholder="Enter a value" /></label>
          </>}
        </div>
        <fieldset className="bounds-grid">
          <legend>Region bounds</legend>
          {(["north", "south", "west", "east"] as const).map((name) => (
            <label key={name}>{fallbackTitle(name)}<input type="number" min={name === "north" || name === "south" ? -90 : -180} max={name === "north" || name === "south" ? 90 : 180} step="0.001" value={form.region[name]} onChange={(e) => changeRegion(name, e.target.value)} /></label>
          ))}
        </fieldset>
        <div className="choice-grid sidebar-choices">
          <SegmentedControl label="Spatial resolution" value={form.coarseness_factor} options={catalog.coarseness_factors.map((item) => ({ value: item, label: spatialResolutionTitle(catalog, selectedDataset, item) }))} onChange={(value) => onChange({ ...form, coarseness_factor: Number(value) })} />
          <SegmentedControl label="Time resolution" value={form.time_unit} options={catalog.time_units.map((item) => ({ value: item, label: item }))} onChange={(value) => onChange({ ...form, time_unit: String(value) })} />
          <SegmentedControl label="Function" value={form.function} options={catalog.functions.map((item) => ({ value: item, label: fallbackTitle(item), title: functionTooltip(item) }))} onChange={(value) => onChange({ ...form, function: String(value) })} />
          <SegmentedControl label="Aggregation" value={form.aggregation_method} options={catalog.aggregation_methods.map((item) => ({ value: item, label: fallbackTitle(item) }))} onChange={(value) => onChange({ ...form, aggregation_method: String(value) })} />
        </div>
      </div>
    </section>
  );
}

type SegmentedOption = { value: string | number; label: string; title?: string };

function SegmentedControl({ label, value, options, onChange }: { label: string; value: string | number; options: SegmentedOption[]; onChange: (value: string | number) => void }) {
  return (
    <fieldset className="segmented-field">
      <legend>{label}</legend>
      <div className="segmented-control">
        {options.map((option) => (
          <button key={String(option.value)} type="button" className={String(value) === String(option.value) ? "active" : ""} title={option.title} onClick={() => onChange(option.value)}>{option.label}</button>
        ))}
      </div>
    </fieldset>
  );
}

function functionTooltip(value: string): string {
  return {
    timeseries: "Aggregate over the region and show one value per time point.",
    heatmap: "Aggregate over time and show one value per spatial cell.",
    "find-time": "Show the complete timeseries and highlight matching times.",
    "find-area": "Show the complete heatmap and outline matching cells.",
    "get-data": "Return the selected data without a derived visualization.",
  }[value] ?? fallbackTitle(value);
}

function AdditionalParameters({ dataset, form, onChange }: { dataset: Dataset; form: QueryForm; onChange: (form: QueryForm) => void }) {
  return <>{Object.entries(dataset.additional_parameters).map(([name, options]) => (
    <label key={name}>{fallbackTitle(name)}<select value={String(form.additional_parameters[name] ?? "")} onChange={(e) => onChange({ ...form, additional_parameters: { ...form.additional_parameters, [name]: e.target.value } })}>{options.map((item) => <option key={String(item)} value={String(item)}>{fallbackTitle(String(item))}</option>)}</select></label>
  ))}</>;
}
