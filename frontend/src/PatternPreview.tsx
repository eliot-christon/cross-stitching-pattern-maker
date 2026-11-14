import { useEffect, useRef } from "react";

import { gridPixels } from "./grid";
import type { Pattern } from "./pattern";

// Largest on-screen cell, in CSS pixels; small patterns stop growing past it.
const MAX_CELL_PX = 12;

// Bare fabric shows through as a checkerboard, so it never reads as a white thread.
const BARE_FABRIC_BACKGROUND = "repeating-conic-gradient(#d8d8d8 0 25%, #f4f4f4 0 50%) 0 0 / 8px 8px";

export function PatternPreview({ pattern }: { pattern: Pattern }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { width, height, finished_size: size } = pattern;

  useEffect(() => {
    // One canvas pixel per cell, scaled up by CSS: a 1000x1000 pattern is one image, not a
    // million elements. jsdom has no 2D context, so the paint is skipped there.
    const context = canvasRef.current?.getContext("2d");
    if (!context) {
      return;
    }
    context.putImageData(new ImageData(gridPixels(pattern), width, height), 0, 0);
  }, [pattern, width, height]);

  return (
    <section>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={`Pattern preview, ${width} x ${height} stitches`}
        width={width}
        height={height}
        style={{
          display: "block",
          width: "100%",
          maxWidth: `${width * MAX_CELL_PX}px`,
          aspectRatio: `${width} / ${height}`,
          imageRendering: "pixelated",
          background: BARE_FABRIC_BACKGROUND,
        }}
      />

      <dl>
        <dt>Size</dt>
        <dd>{`${width} x ${height} stitches`}</dd>
        <dt>Fabric</dt>
        <dd>{`${pattern.fabric_count} count`}</dd>
        <dt>Stitches</dt>
        <dd>{`${pattern.total_stitches} stitches in total`}</dd>
        <dt>Finished size</dt>
        <dd>{`${size.width_in.toFixed(1)} x ${size.height_in.toFixed(1)} in`}</dd>
        <dd>{`${size.width_cm.toFixed(1)} x ${size.height_cm.toFixed(1)} cm`}</dd>
      </dl>

      <table>
        <caption>Thread key</caption>
        <thead>
          <tr>
            <td />
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
