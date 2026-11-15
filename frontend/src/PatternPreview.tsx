import type { Pattern } from "./pattern";
import { PatternViewer } from "./PatternViewer";

/** The key's columns after the swatch, as their headers read. */
const COLUMNS = ["Symbol", "Code", "Name", "Stitches", "Skeins"] as const;

export function PatternPreview({ pattern }: { pattern: Pattern }) {
  const { width, height, finished_size: size } = pattern;

  return (
    <section className="preview">
      <PatternViewer pattern={pattern} />

      <dl className="summary">
        <div>
          <dt>Size</dt>
          <dd>{`${width} x ${height} stitches`}</dd>
        </div>
        <div>
          <dt>Fabric</dt>
          <dd>{`${pattern.fabric_count} count`}</dd>
        </div>
        <div>
          <dt>Stitches</dt>
          <dd>{`${pattern.total_stitches} stitches in total`}</dd>
        </div>
        <div>
          <dt>Isolated stitches</dt>
          <dd>{`${pattern.isolated_stitches.before} before cleanup`}</dd>
          <dd>{`${pattern.isolated_stitches.after} after cleanup`}</dd>
        </div>
        <div>
          <dt>Finished size</dt>
          <dd>{`${size.width_in.toFixed(1)} x ${size.height_in.toFixed(1)} in`}</dd>
          <dd>{`${size.width_cm.toFixed(1)} x ${size.height_cm.toFixed(1)} cm`}</dd>
        </div>
      </dl>

      {/* Explicit roles: below 800 px the rows are laid out as cards, and some browsers
          drop a table's semantics when CSS changes its display. */}
      <table className="key" role="table">
        <caption>Thread key</caption>
        <thead>
          <tr role="row">
            <td role="cell" />
            {COLUMNS.map((column) => (
              <th key={column} scope="col" role="columnheader">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {pattern.key.map((entry) => (
            <tr key={entry.code} role="row" className="key-entry">
              <td role="cell" className="key-swatch">
                <span
                  aria-hidden="true"
                  className="swatch"
                  style={{ backgroundColor: `rgb(${entry.rgb.join(", ")})` }}
                />
              </td>
              <td role="cell" className="key-symbol">
                {entry.symbol}
              </td>
              <td role="cell" className="key-code">
                {entry.code}
              </td>
              <td role="cell" className="key-name">
                {entry.name}
              </td>
              <td role="cell" className="key-count" data-label="Stitches">
                {String(entry.stitches)}
              </td>
              <td role="cell" className="key-count" data-label="Skeins">
                {String(entry.skeins)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
