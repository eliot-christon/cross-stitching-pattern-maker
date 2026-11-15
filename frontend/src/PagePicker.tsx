import { useLayoutEffect, useMemo, useRef, useState } from "react";

import type { ChartLayout, ChartLayoutReport, ChartOptions } from "./api";
import { gridPixels } from "./grid";
import type { Pattern } from "./pattern";

/** Page counts shown at first, each way; "More page counts" shows up to the API's 20. */
const FIRST_SHOWN = 8;
/** The section preview's largest size, in CSS px. */
const PREVIEW_MAX = { width: 300, height: 220 };

type Cells = Pick<Pattern, "width" | "height" | "grid" | "key">;

function parseCount(value: string): number | null {
  const count = Number(value);
  return Number.isInteger(count) && count >= 1 ? count : null;
}

/** What a split of `across` x `down` pages gives, as the API reported it. */
function describe(report: ChartLayoutReport | null, across: number, down: number): string {
  const pages = `${across} × ${down} = ${across * down} ${across * down === 1 ? "page" : "pages"}`;
  const option = report?.pages[down - 1]?.[across - 1];
  if (option === undefined) {
    return pages;
  }
  if (option.cell_mm === null) {
    return `${pages}: cells would be under 2 mm`;
  }
  return `${pages}, ${option.cell_mm.toFixed(1)} mm cells, up to ${option.columns} × ${option.rows} cells each`;
}

/**
 * The pages split as a grid of sheets, shaped like the paper as it is turned: a sheet at
 * column a and row d stands for a x d pages. Hovering or focusing one previews it,
 * clicking picks it; the splits the API refuses (cells under 2 mm) are disabled.
 */
export function PagePicker(props: {
  report: ChartLayoutReport | null;
  orientation: ChartOptions["orientation"];
  across: string;
  down: string;
  onPick: (across: number, down: number) => void;
}) {
  const { report, orientation, across, down, onPick } = props;
  const chosen = { across: parseCount(across) ?? 0, down: parseCount(down) ?? 0 };
  const available = report?.pages.length ?? FIRST_SHOWN;
  const [more, setMore] = useState(Math.max(chosen.across, chosen.down) > FIRST_SHOWN);
  const [hovered, setHovered] = useState<{ across: number; down: number } | null>(null);
  const size = Math.min(more ? available : FIRST_SHOWN, available);
  const shown = hovered ?? chosen;
  const counts = Array.from({ length: size }, (_, i) => i + 1);

  return (
    <div className="page-picker">
      <p className="page-picker-summary" aria-live="polite">
        {shown.across > 0 && shown.down > 0 ? describe(report, shown.across, shown.down) : "Pick the pages"}
      </p>
      <div
        className={`page-grid page-grid-${orientation}`}
        role="group"
        aria-label="Pages across and down"
        style={{ gridTemplateColumns: `repeat(${size}, auto)` }}
        onMouseLeave={() => setHovered(null)}
      >
        {counts.flatMap((d) =>
          counts.map((a) => {
            const option = report?.pages[d - 1]?.[a - 1];
            const refused = option !== undefined && option.cell_mm === null;
            const inShown = a <= shown.across && d <= shown.down;
            const isChosen = a === chosen.across && d === chosen.down;
            const classes = ["page-cell", inShown && "in-range", isChosen && "is-chosen"]
              .filter(Boolean)
              .join(" ");
            return (
              <button
                key={`${a}-${d}`}
                type="button"
                className={classes}
                aria-label={`${a} across, ${d} down`}
                aria-pressed={isChosen}
                disabled={refused}
                title={describe(report, a, d)}
                onMouseEnter={() => setHovered({ across: a, down: d })}
                onFocus={() => setHovered({ across: a, down: d })}
                onBlur={() => setHovered(null)}
                onClick={() => onPick(a, d)}
              />
            );
          }),
        )}
      </div>
      {available > FIRST_SHOWN && (
        <button type="button" className="link-button" onClick={() => setMore(!more)}>
          {more ? "Fewer page counts" : "More page counts"}
        </button>
      )}
    </div>
  );
}

/** The pattern as small as it fits the preview box, one rectangle per cell. */
function previewScale(cells: Cells): number {
  return Math.min(PREVIEW_MAX.width / cells.width, PREVIEW_MAX.height / cells.height);
}

/**
 * The pattern's thumbnail with each chart section outlined and named, as the PDF's
 * section plan shows it; bare fabric in the fabric colour.
 */
export function SectionPreview(props: { pattern: Cells; layout: ChartLayout | null; fabric: string }) {
  const { pattern, layout, fabric } = props;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pixels = useMemo(() => gridPixels(pattern), [pattern]);
  const scale = previewScale(pattern);
  const width = Math.max(1, Math.round(pattern.width * scale));
  const height = Math.max(1, Math.round(pattern.height * scale));

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) {
      return;
    }
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.fillStyle = fabric;
    context.fillRect(0, 0, width, height);
    const source = document.createElement("canvas");
    source.width = pattern.width;
    source.height = pattern.height;
    source.getContext("2d")?.putImageData(new ImageData(pixels, pattern.width, pattern.height), 0, 0);
    context.imageSmoothingEnabled = false;
    context.drawImage(source, 0, 0, width, height);
    if (layout === null) {
      return;
    }
    const sx = width / pattern.width;
    const sy = height / pattern.height;
    context.lineWidth = 1.5;
    context.font = "600 11px system-ui, sans-serif";
    context.textBaseline = "top";
    layout.rows.forEach((row, r) => {
      layout.columns.forEach((column, c) => {
        const x = column.start * sx;
        const y = row.start * sy;
        context.strokeStyle = "rgba(20, 16, 12, 0.85)";
        context.strokeRect(x + 0.75, y + 0.75, (column.end - column.start) * sx - 1.5, (row.end - row.start) * sy - 1.5);
        const name = layout.sections[r]?.[c] ?? "";
        const tab = context.measureText(name).width + 6;
        context.fillStyle = "rgba(255, 255, 255, 0.9)";
        context.fillRect(x + 2, y + 2, tab, 14);
        context.fillStyle = "#1d1a16";
        context.fillText(name, x + 5, y + 4);
      });
    });
  }, [pattern, pixels, layout, fabric, width, height]);

  const sections = layout === null ? 0 : layout.columns.length * layout.rows.length;
  const label =
    layout === null
      ? "Chart sections"
      : `Chart sections: ${sections} ${sections === 1 ? "page" : "pages"}, ${layout.columns.length} across, ${layout.rows.length} down`;
  return (
    <figure className="section-preview">
      <canvas ref={canvasRef} role="img" aria-label={label} style={{ width, height }} />
      {layout !== null && (
        <figcaption>
          {`${layout.sections[0]?.[0] ?? ""}-${layout.sections.at(-1)?.at(-1) ?? ""}: ${sections} ${sections === 1 ? "page" : "pages"} of ${layout.cell_mm.toFixed(1)} mm cells`}
        </figcaption>
      )}
    </figure>
  );
}
