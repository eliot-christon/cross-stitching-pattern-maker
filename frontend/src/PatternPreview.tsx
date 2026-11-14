import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { gridPixels } from "./grid";
import type { Pattern } from "./pattern";
import { visibleSymbols } from "./symbolView";

// Largest on-screen cell, in CSS pixels; small patterns stop growing past it.
const MAX_CELL_PX = 12;

// Bare fabric shows through as a checkerboard, so it never reads as a white thread.
const BARE_FABRIC_BACKGROUND = "repeating-conic-gradient(#d8d8d8 0 25%, #f4f4f4 0 50%) 0 0 / 8px 8px";

// Symbol view: every cell keeps this size, large enough to read its symbol.
const SYMBOL_CELL_PX = 16;
const SYMBOL_FONT = `${SYMBOL_CELL_PX - 4}px "DejaVu Sans", "Segoe UI Symbol", sans-serif`;
const SYMBOL_BOX_MAX_HEIGHT = "70vh";
const BARE_CELL_FILL = "#e2e2e2";
const GRID_LINE = "#c8c8c8";

type ViewMode = "colours" | "symbols";

export function PatternPreview({ pattern }: { pattern: Pattern }) {
  const [mode, setMode] = useState<ViewMode>("colours");
  const { width, height, finished_size: size } = pattern;

  return (
    <section>
      <fieldset>
        <legend>View</legend>
        <label>
          <input
            type="radio"
            name="preview-view"
            checked={mode === "colours"}
            onChange={() => setMode("colours")}
          />
          Colours
        </label>
        <label>
          <input
            type="radio"
            name="preview-view"
            checked={mode === "symbols"}
            onChange={() => setMode("symbols")}
          />
          Symbols
        </label>
      </fieldset>

      {mode === "colours" ? <ColourGrid pattern={pattern} /> : <SymbolGrid pattern={pattern} />}

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

function ColourGrid({ pattern }: { pattern: Pattern }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { width, height } = pattern;

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
  );
}

/** Paint the cells under the box's scroll position onto the canvas, which is box-sized. */
function paintSymbols(box: HTMLElement, canvas: HTMLCanvasElement, pattern: Pattern) {
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }
  const { scrollLeft: left, scrollTop: top, clientWidth: width, clientHeight: height } = box;
  const ratio = window.devicePixelRatio || 1;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  canvas.width = Math.ceil(width * ratio);
  canvas.height = Math.ceil(height * ratio);
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.font = SYMBOL_FONT;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.lineWidth = 1;
  context.strokeStyle = GRID_LINE;

  const view = {
    firstColumn: Math.floor(left / SYMBOL_CELL_PX),
    firstRow: Math.floor(top / SYMBOL_CELL_PX),
    columns: Math.ceil(width / SYMBOL_CELL_PX) + 1,
    rows: Math.ceil(height / SYMBOL_CELL_PX) + 1,
  };
  for (const cell of visibleSymbols(pattern, view)) {
    const x = cell.column * SYMBOL_CELL_PX - left;
    const y = cell.row * SYMBOL_CELL_PX - top;
    context.fillStyle = cell.symbol === null ? BARE_CELL_FILL : "#fff";
    context.fillRect(x, y, SYMBOL_CELL_PX, SYMBOL_CELL_PX);
    context.strokeRect(x + 0.5, y + 0.5, SYMBOL_CELL_PX - 1, SYMBOL_CELL_PX - 1);
    if (cell.symbol !== null) {
      context.fillStyle = "#000";
      context.fillText(cell.symbol, x + SYMBOL_CELL_PX / 2, y + SYMBOL_CELL_PX / 2 + 1);
    }
  }
}

function SymbolGrid({ pattern }: { pattern: Pattern }) {
  // A scrollable box over a spacer the size of the whole chart. The canvas is only as big
  // as the box and sticks to its top-left corner, so a 1000x1000 pattern draws a few
  // thousand cells at a time, never a million; each scroll repaints it directly.
  const boxRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { width, height } = pattern;

  useLayoutEffect(() => {
    const box = boxRef.current;
    const canvas = canvasRef.current;
    if (!box || !canvas) {
      return;
    }
    const paint = () => paintSymbols(box, canvas, pattern);
    paint();
    box.addEventListener("scroll", paint, { passive: true });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(paint);
    observer?.observe(box);
    return () => {
      box.removeEventListener("scroll", paint);
      observer?.disconnect();
    };
  }, [pattern]);

  return (
    <div
      ref={boxRef}
      tabIndex={0}
      style={{
        overflow: "auto",
        width: "fit-content",
        maxWidth: "100%",
        maxHeight: SYMBOL_BOX_MAX_HEIGHT,
        border: "1px solid #888",
      }}
    >
      <div
        style={{
          width: `${width * SYMBOL_CELL_PX}px`,
          height: `${height * SYMBOL_CELL_PX}px`,
        }}
      >
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={`Pattern symbols, ${width} x ${height} stitches`}
          style={{ display: "block", position: "sticky", top: 0, left: 0 }}
        />
      </div>
    </div>
  );
}
