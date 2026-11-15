import type { Pattern } from "./pattern";
import { PatternViewer } from "./PatternViewer";

export function PatternPreview({ pattern }: { pattern: Pattern }) {
  const { width, height, finished_size: size } = pattern;

  return (
    <section>
      <PatternViewer pattern={pattern} />

      <dl>
        <dt>Size</dt>
        <dd>{`${width} x ${height} stitches`}</dd>
        <dt>Fabric</dt>
        <dd>{`${pattern.fabric_count} count`}</dd>
        <dt>Stitches</dt>
        <dd>{`${pattern.total_stitches} stitches in total`}</dd>
        <dt>Isolated stitches</dt>
        <dd>{`${pattern.isolated_stitches.before} before cleanup`}</dd>
        <dd>{`${pattern.isolated_stitches.after} after cleanup`}</dd>
        <dt>Finished size</dt>
        <dd>{`${size.width_in.toFixed(1)} x ${size.height_in.toFixed(1)} in`}</dd>
        <dd>{`${size.width_cm.toFixed(1)} x ${size.height_cm.toFixed(1)} cm`}</dd>
      </dl>

      <table>
        <caption>Thread key</caption>
        <thead>
          <tr>
            <td />
            <th scope="col">Symbol</th>
            <th scope="col">Code</th>
            <th scope="col">Name</th>
            <th scope="col">Stitches</th>
            <th scope="col">Skeins</th>
          </tr>
        </thead>
        <tbody>
          {pattern.key.map((entry) => (
            <tr key={entry.code}>
              <td>
                <span
                  aria-hidden="true"
                  style={{
                    display: "inline-block",
                    width: "1em",
                    height: "1em",
                    border: "1px solid #888",
                    background: `rgb(${entry.rgb.join(" ")})`,
                  }}
                />
              </td>
              <td>{entry.symbol}</td>
              <td>{entry.code}</td>
              <td>{entry.name}</td>
              <td>{String(entry.stitches)}</td>
              <td>{String(entry.skeins)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
