import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { centreLines, tenCellLines } from "./chartAids";
import { Segmented, Switch } from "./controls";
import { DEFAULT_FABRIC } from "./fabric";
import { gridPixels } from "./grid";
import type { Pattern } from "./pattern";
import { rgbCss } from "./swatch";
import { visibleCells, visibleSymbols, type View } from "./symbolView";
import {
  fitViewport,
  maxScale,
  panBy,
  pinchFactor,
  resizeViewer,
  visibleWindow,
  wheelFactor,
  zoomAt,
  type Point,
  type Size,
  type Viewport,
} from "./viewport";

type Cells = Pick<Pattern, "width" | "height" | "grid" | "key">;

export type ViewMode = "colours" | "symbols" | "symbols-on-colours";

/** Smallest cell, in CSS px, whose symbol can be read; below it no symbol is drawn. */
export const SYMBOL_MIN_PX = 12;
/** One press of Zoom in / Zoom out, or of + / -, scales by this. */
const ZOOM_STEP = 1.25;
/** One arrow key press pans by this many CSS px. */
const PAN_STEP = 48;

// Symbols mode keeps the printed chart's look in both themes: black on white.
const SYMBOL_CELL = "#ffffff";
const SYMBOL_INK = "#000000";
const BARE_CELL = "#e2e2e2";
const CELL_LINE = "#c8c8c8";
// The chart aids: 10-cell lines as the PDF's bold lines, centre lines in red.
const TEN_LINE = "rgba(20, 16, 12, 0.6)";
const TEN_LINE_WIDTH = 1.5;
const CENTRE_LINE = "#d62828";
const CENTRE_LINE_WIDTH = 2;
const INK = { black: "#000000", white: "#ffffff" } as const;

const EMPTY_SIZE: Size = { width: 0, height: 0 };

function atScale(a: number, b: number): boolean {
  return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(b));
}

/** The pattern's colours as a W x H image, one pixel per cell; null where there is no 2D. */
function colourSource(cells: Cells): HTMLCanvasElement | null {
  const canvas = document.createElement("canvas");
  canvas.width = cells.width;
  canvas.height = cells.height;
  const context = canvas.getContext("2d");
  if (!context || cells.width === 0 || cells.height === 0) {
    return null;
  }
  context.putImageData(new ImageData(gridPixels(cells), cells.width, cells.height), 0, 0);
  return canvas;
}

/** The window's rectangle in viewer px. */
function windowRect(vp: Viewport, view: View) {
  return {
    x: vp.x + view.firstColumn * vp.scale,
    y: vp.y + view.firstRow * vp.scale,
    width: view.columns * vp.scale,
    height: view.rows * vp.scale,
  };
}

/** The cells in view as colours, bare fabric in the `fabric` colour under them. */
function paintColours(
  context: CanvasRenderingContext2D,
  vp: Viewport,
  view: View,
  source: HTMLCanvasElement | null,
  fabric: string,
) {
  const rect = windowRect(vp, view);
  context.fillStyle = fabric;
  context.fillRect(rect.x, rect.y, rect.width, rect.height);
  if (source === null) {
    return;
  }
  context.imageSmoothingEnabled = false;
  // Only the cells in view are copied: one image draw, whatever the pattern's size.
  context.drawImage(
    source,
    view.firstColumn,
    view.firstRow,
    view.columns,
    view.rows,
    rect.x,
    rect.y,
    rect.width,
    rect.height,
  );
}

/** The symbol font for cells of `scale` CSS px. */
function symbolFont(scale: number): string {
  return `${Math.round(scale * 0.72)}px "DejaVu Sans", "Segoe UI Symbol", sans-serif`;
}

function paintSymbols(
  context: CanvasRenderingContext2D,
  vp: Viewport,
  view: View,
  cells: Cells,
) {
  const { scale } = vp;
  context.font = symbolFont(scale);
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.lineWidth = 1;
  context.strokeStyle = CELL_LINE;
  for (const cell of visibleSymbols(cells, view)) {
    const x = vp.x + cell.column * scale;
    const y = vp.y + cell.row * scale;
    context.fillStyle = cell.symbol === null ? BARE_CELL : SYMBOL_CELL;
    context.fillRect(x, y, scale, scale);
    context.strokeRect(x + 0.5, y + 0.5, scale - 1, scale - 1);
    if (cell.symbol !== null) {
      context.fillStyle = SYMBOL_INK;
      context.fillText(cell.symbol, x + scale / 2, y + scale / 2 + 1);
    }
  }
}

/** Each cell in view filled with its thread's colour, its symbol in the entry's ink; bare
 * fabric in the `fabric` colour. */
function paintSymbolsOnColours(
  context: CanvasRenderingContext2D,
  vp: Viewport,
  view: View,
  cells: Cells,
  fabric: string,
) {
  const { scale } = vp;
  context.font = symbolFont(scale);
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.lineWidth = 1;
  context.strokeStyle = "rgba(0, 0, 0, 0.15)";
  for (const { column, row, entry } of visibleCells(cells, view)) {
    const x = vp.x + column * scale;
    const y = vp.y + row * scale;
    if (entry === null) {
      context.fillStyle = fabric;
      context.fillRect(x, y, scale, scale);
      continue;
    }
    context.fillStyle = rgbCss(entry.rgb);
    context.fillRect(x, y, scale, scale);
    context.strokeRect(x + 0.5, y + 0.5, scale - 1, scale - 1);
    context.fillStyle = INK[entry.symbol_ink];
    context.fillText(entry.symbol, x + scale / 2, y + scale / 2 + 1);
  }
}

function strokeLines(
  context: CanvasRenderingContext2D,
  colour: string,
  width: number,
  lines: { x1: number; y1: number; x2: number; y2: number }[],
) {
  if (lines.length === 0) {
    return;
  }
  context.strokeStyle = colour;
  context.lineWidth = width;
  context.beginPath();
  for (const line of lines) {
    context.moveTo(line.x1, line.y1);
    context.lineTo(line.x2, line.y2);
  }
  context.stroke();
}

/** The 10-cell lines and, when asked, the centre lines, over the window. */
function paintAids(
  context: CanvasRenderingContext2D,
  vp: Viewport,
  view: View,
  pattern: Size,
  centre: boolean,
) {
  const rect = windowRect(vp, view);
  const ten = tenCellLines(view, pattern, vp.scale);
  strokeLines(context, TEN_LINE, TEN_LINE_WIDTH, [
    ...ten.columns.map((column) => {
      const x = vp.x + column * vp.scale;
      return { x1: x, y1: rect.y, x2: x, y2: rect.y + rect.height };
    }),
    ...ten.rows.map((row) => {
      const y = vp.y + row * vp.scale;
      return { x1: rect.x, y1: y, x2: rect.x + rect.width, y2: y };
    }),
  ]);
  if (centre) {
    const middle = centreLines(pattern);
    const x = vp.x + middle.column * vp.scale;
    const y = vp.y + middle.row * vp.scale;
    strokeLines(context, CENTRE_LINE, CENTRE_LINE_WIDTH, [
      { x1: x, y1: rect.y, x2: x, y2: rect.y + rect.height },
      { x1: rect.x, y1: y, x2: rect.x + rect.width, y2: y },
    ]);
  }
}

function canvasName(mode: ViewMode, before: boolean | null, cells: Cells): string {
  const size = `${cells.width} x ${cells.height} stitches`;
  if (mode === "symbols") {
    return `Pattern symbols, ${size}`;
  }
  if (mode === "symbols-on-colours") {
    return `Pattern symbols on colours, ${size}`;
  }
  if (before === null) {
    return `Pattern preview, ${size}`;
  }
  return `${before ? "Before" : "After"} cleanup, ${size}`;
}

/** The viewer's box size, kept up to date where `ResizeObserver` exists. */
function useBoxSize(ref: React.RefObject<HTMLElement | null>): Size {
  const [size, setSize] = useState<Size>(EMPTY_SIZE);
  useLayoutEffect(() => {
    const box = ref.current;
    if (!box) {
      return;
    }
    const measure = () => {
      const next = { width: box.clientWidth, height: box.clientHeight };
      setSize((current) =>
        current.width === next.width && current.height === next.height ? current : next,
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

/**
 * The pattern on one canvas, zoomable and pannable: Colours or Symbols, and, when the
 * response has the pattern before cleanup, Before / After in Colours.
 */
export type ViewerShows = "pattern" | "pdf";

export function PatternViewer(props: {
  pattern: Pattern;
  /** The PDF view, behind a Pattern / PDF switch; none, no switch. */
  pdfView?: ReactNode;
  onShowChange?: (shows: ViewerShows) => void;
  /** The fabric's colour, which bare cells show in Colours and Symbols on colours. */
  fabric?: string;
}) {
  const { pattern, pdfView, onShowChange, fabric = DEFAULT_FABRIC } = props;
  const [shows, setShows] = useState<ViewerShows>("pattern");
  const pdf = pdfView !== undefined && shows === "pdf";
  const [mode, setMode] = useState<ViewMode>("colours");
  const [showBefore, setShowBefore] = useState(false);
  const [centreLinesOn, setCentreLinesOn] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const size = useBoxSize(boxRef);

  const { width, height, converted } = pattern;
  const dims = useMemo(() => ({ width, height }), [width, height]);
  const before = useMemo(
    () => (converted === null ? null : { width, height, grid: converted.grid, key: converted.key }),
    [converted, width, height],
  );
  const shown: Cells = mode === "colours" && showBefore && before !== null ? before : pattern;

  const afterSource = useMemo(() => colourSource(pattern), [pattern]);
  const beforeSource = useMemo(
    () => (before !== null && showBefore ? colourSource(before) : null),
    [before, showBefore],
  );
  const source = shown === pattern ? afterSource : beforeSource;

  // The viewport, with the pattern size and the box size it was computed for: a new size of
  // either refits or re-anchors it before it is used.
  const [state, setState] = useState(() => ({ vp: fitViewport(dims, size), dims, size }));
  let { vp } = state;
  if (state.dims !== dims || state.size !== size) {
    const sameDims = state.dims.width === dims.width && state.dims.height === dims.height;
    vp = sameDims ? resizeViewer(vp, dims, state.size, size) : fitViewport(dims, size);
    setState({ vp, dims, size });
  }
  // What the native wheel listener reads: it is added once and outlives every render.
  const latest = useRef({ dims, size });
  useLayoutEffect(() => {
    latest.current = { dims, size };
  }, [dims, size]);

  function update(next: (current: Viewport) => Viewport) {
    setState((current) => ({ ...current, vp: next(current.vp) }));
  }

  const fit = fitViewport(dims, size).scale;
  const atFit = atScale(vp.scale, fit);
  const atMax = vp.scale >= maxScale(dims, size) || atScale(vp.scale, maxScale(dims, size));
  const centre: Point = { x: size.width / 2, y: size.height / 2 };
  const readable = vp.scale >= SYMBOL_MIN_PX;

  function zoomBy(factor: number, point: Point = centre) {
    update((current) => zoomAt(current, dims, size, factor, point));
  }

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) {
      return;
    }
    const ratio = window.devicePixelRatio || 1;
    const pixelWidth = Math.round(size.width * ratio);
    const pixelHeight = Math.round(size.height * ratio);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, size.width, size.height);
    const view = visibleWindow(vp, dims, size);
    if (view.columns === 0 || view.rows === 0) {
      return;
    }
    if (mode === "symbols" && readable) {
      paintSymbols(context, vp, view, pattern);
    } else if (mode === "symbols-on-colours" && readable) {
      paintSymbolsOnColours(context, vp, view, pattern, fabric);
    } else {
      paintColours(context, vp, view, source, fabric);
    }
    paintAids(context, vp, view, dims, centreLinesOn);
  }, [vp, dims, size, mode, readable, pattern, source, centreLinesOn, fabric]);

  // The wheel zooms about the pointer. A native listener, because React's is passive and
  // the page must not scroll while the wheel zooms.
  useEffect(() => {
    const box = boxRef.current;
    if (!box) {
      return;
    }
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? box.clientHeight : 1;
      const bounds = box.getBoundingClientRect();
      const point = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
      const { dims: d, size: s } = latest.current;
      setState((current) => ({
        ...current,
        vp: zoomAt(current.vp, d, s, wheelFactor(event.deltaY * unit), point),
      }));
    };
    box.addEventListener("wheel", onWheel, { passive: false });
    return () => box.removeEventListener("wheel", onWheel);
  }, []);

  // Drag pans; two pointers pinch about their midpoint.
  const pointers = useRef(new Map<number, Point>());

  function local(event: React.PointerEvent): Point {
    const bounds = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
  }

  function onPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    event.currentTarget.setPointerCapture?.(event.pointerId);
    pointers.current.set(event.pointerId, local(event));
  }

  function onPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const previous = pointers.current.get(event.pointerId);
    if (previous === undefined) {
      return;
    }
    const point = local(event);
    const others = [...pointers.current.entries()].filter(([id]) => id !== event.pointerId);
    pointers.current.set(event.pointerId, point);
    const other = others[0]?.[1];
    if (other === undefined) {
      update((current) => panBy(current, dims, size, point.x - previous.x, point.y - previous.y));
      return;
    }
    const from = Math.hypot(previous.x - other.x, previous.y - other.y);
    const to = Math.hypot(point.x - other.x, point.y - other.y);
    const midFrom = { x: (previous.x + other.x) / 2, y: (previous.y + other.y) / 2 };
    const midTo = { x: (point.x + other.x) / 2, y: (point.y + other.y) / 2 };
    update((current) =>
      panBy(
        zoomAt(current, dims, size, pinchFactor(from, to), midFrom),
        dims,
        size,
        midTo.x - midFrom.x,
        midTo.y - midFrom.y,
      ),
    );
  }

  function onPointerUp(event: React.PointerEvent<HTMLDivElement>) {
    pointers.current.delete(event.pointerId);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const pans: Record<string, [number, number]> = {
      ArrowLeft: [PAN_STEP, 0],
      ArrowRight: [-PAN_STEP, 0],
      ArrowUp: [0, PAN_STEP],
      ArrowDown: [0, -PAN_STEP],
    };
    const pan = pans[event.key];
    if (pan !== undefined) {
      update((current) => panBy(current, dims, size, pan[0], pan[1]));
    } else if (event.key === "+" || event.key === "=") {
      zoomBy(ZOOM_STEP);
    } else if (event.key === "-" || event.key === "_") {
      zoomBy(1 / ZOOM_STEP);
    } else if (event.key === "0") {
      update(() => fitViewport(dims, size));
    } else {
      return;
    }
    event.preventDefault();
  }

  const label = canvasName(mode, before === null ? null : shown !== pattern, shown);

  return (
    <div className="viewer">
      <div className="viewer-toolbar">
        {pdfView !== undefined && (
          <Segmented
            legend="Show"
            options={[
              { value: "pattern", label: "Pattern" },
              { value: "pdf", label: "PDF" },
            ]}
            value={shows}
            onChange={(value) => {
              setShows(value);
              onShowChange?.(value);
            }}
          />
        )}
        <div className="viewer-controls" hidden={pdf}>
        <Segmented
          legend="View"
          options={[
            { value: "colours", label: "Colours" },
            { value: "symbols", label: "Symbols" },
            { value: "symbols-on-colours", label: "Symbols on colours" },
          ]}
          value={mode}
          onChange={setMode}
        />
        {before !== null && mode === "colours" && (
          <Segmented
            legend="Cleanup"
            options={[
              { value: "before", label: "Before cleanup" },
              { value: "after", label: "After cleanup" },
            ]}
            value={showBefore ? "before" : "after"}
            onChange={(value) => setShowBefore(value === "before")}
          />
        )}
        <Switch label="Centre lines" checked={centreLinesOn} onChange={setCentreLinesOn} />
        <div className="viewer-zoom">
          <button
            type="button"
            className="icon-button"
            aria-label="Zoom out"
            disabled={atFit}
            onClick={() => zoomBy(1 / ZOOM_STEP)}
          >
            −
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Zoom in"
            disabled={atMax}
            onClick={() => zoomBy(ZOOM_STEP)}
          >
            +
          </button>
          <button
            type="button"
            className="button"
            disabled={atFit}
            onClick={() => update(() => fitViewport(dims, size))}
          >
            Fit
          </button>
        </div>
        </div>
      </div>
      {pdf && pdfView}
      <div
        ref={boxRef}
        hidden={pdf}
        className="viewer-box"
        role="group"
        tabIndex={0}
        aria-label="Pattern viewer: drag to pan, wheel or + and - to zoom, arrows to move"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
      >
        <canvas ref={canvasRef} role="img" aria-label={label} />
      </div>
      {!pdf && mode !== "colours" && !readable && (
        <p className="viewer-hint">Zoom in to read the symbols.</p>
      )}
    </div>
  );
}
