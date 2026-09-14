import type { AvailabilityRow } from "./types";

type Props = {
  rows: AvailabilityRow[];
  loading: boolean;
  error: string;
  onClose: () => void;
};

const label = (value: string) =>
  value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());

const parameters = (values: Record<string, unknown>) =>
  Object.entries(values)
    .map(([name, value]) => `${label(name)}: ${String(value)}`)
    .join(", ") || "—";

export default function AvailabilityTable({ rows, loading, error, onClose }: Props) {
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="availability-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="availability-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-heading">
          <div>
            <p className="eyebrow">Storage index</p>
            <h2 id="availability-title">Available data</h2>
          </div>
          <button className="secondary-button" type="button" onClick={onClose}>Close</button>
        </div>
        {loading && <div className="dialog-state"><div className="spinner" /><p>Reading storage metadata…</p></div>}
        {error && <div className="message error" role="alert">{error}</div>}
        {!loading && !error && rows.length === 0 && <div className="dialog-state"><p>No native data was found in the storage index.</p></div>}
        {!loading && rows.length > 0 && (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Repository / dataset</th><th>Variable</th><th>Parameters</th><th>Region (W, E, S, N)</th><th>Time interval</th><th>Source resolution</th></tr></thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={`${row.repository}-${row.dataset}-${row.variable}-${index}`}>
                    <td><strong>{label(row.repository)}</strong><span>{label(row.dataset)}</span></td>
                    <td>{label(row.variable)}</td>
                    <td>{parameters(row.additional_parameters)}</td>
                    <td>{row.region.west}, {row.region.east}, {row.region.south}, {row.region.north}</td>
                    <td>{row.time_start.slice(0, 10)}<span>through {row.time_end.slice(0, 10)}</span></td>
                    <td>{row.spatial_resolutions.join(", ")}<span>{row.temporal_resolutions.join(", ")}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
