/**
 * The pattern viewer's coordinate model: how big a cell is on screen and where the
 * pattern sits in the viewer, with fit, zoom about a point, pan, resize and the window of
 * cells in view. Pure: no DOM, no React.
 *
 * Lengths are CSS px in the viewer and cells in the pattern. Every function is total: an
 * empty viewer or pattern gives finite numbers and an empty window, never NaN or Infinity.
 */
import type { View } from "./symbolView";

/** A size in CSS px (the viewer) or in cells (the pattern). */
export interface Size {
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

/** `scale` is CSS px per cell; (`x`, `y`) is the pattern's top-left corner in the viewer. */
export interface Viewport {
  scale: number;
  x: number;
  y: number;
}

/** The largest cell, in CSS px, zooming in can reach (unless fitting needs more). */
export const MAX_CELL_PX = 64;

/** How fast the wheel zooms: the factor for a delta of `d` px is `exp(-d * WHEEL_RATE)`. */
const WHEEL_RATE = 0.0015;
/** The exponent's bound, so a huge delta gives a huge but finite factor (e^20, about 5e8). */
const WHEEL_EXPONENT_MAX = 20;

function finite(value: number, fallback = 0): number {
  return Number.isFinite(value) ? value : fallback;
}

function isEmpty(size: Size): boolean {
  return !(size.width > 0 && size.height > 0);
}

/** The largest scale that shows the whole pattern; 0 when either size is empty. */
function fitScale(pattern: Size, viewer: Size): number {
  if (isEmpty(pattern) || isEmpty(viewer)) {
    return 0;
  }
  return finite(Math.min(viewer.width / pattern.width, viewer.height / pattern.height));
}

/**
 * Where the pattern goes along one axis: centred when it fits in the viewer, otherwise
 * kept so that no gap opens between its edge and the viewer's.
 */
function placeAxis(position: number, patternPx: number, viewerPx: number): number {
  if (patternPx <= viewerPx) {
    return (viewerPx - patternPx) / 2;
  }
  return Math.min(0, Math.max(viewerPx - patternPx, position));
}

function clampViewport(vp: Viewport, pattern: Size, viewer: Size): Viewport {
  const scale = finite(vp.scale);
  return {
    scale,
    x: finite(placeAxis(finite(vp.x), scale * pattern.width, viewer.width)),
    y: finite(placeAxis(finite(vp.y), scale * pattern.height, viewer.height)),
  };
}

/** The whole pattern, as large as the viewer allows, centred. */
export function fitViewport(pattern: Size, viewer: Size): Viewport {
  return clampViewport({ scale: fitScale(pattern, viewer), x: 0, y: 0 }, pattern, viewer);
}

/** The largest scale zooming in reaches: `MAX_CELL_PX`, or the fit if that is larger. */
export function maxScale(pattern: Size, viewer: Size): number {
  return Math.max(fitScale(pattern, viewer), MAX_CELL_PX);
}

/**
 * Zoom by `factor` about `point` (viewer px): the pattern point under it stays under it,
 * unless the scale hits fit or `maxScale`, or the pan limits move the pattern.
 */
export function zoomAt(
  vp: Viewport,
  pattern: Size,
  viewer: Size,
  factor: number,
  point: Point,
): Viewport {
  const fit = fitScale(pattern, viewer);
  if (!(vp.scale > 0) || fit === 0) {
    return fitViewport(pattern, viewer);
  }
  const wanted = vp.scale * finite(factor, 1);
  const scale = Math.min(maxScale(pattern, viewer), Math.max(fit, finite(wanted, vp.scale)));
  const ratio = scale / vp.scale;
  return clampViewport(
    {
      scale,
      x: point.x - (point.x - vp.x) * ratio,
      y: point.y - (point.y - vp.y) * ratio,
    },
    pattern,
    viewer,
  );
}

/** Move the pattern by (`dx`, `dy`) viewer px, within the pan limits. */
export function panBy(
  vp: Viewport,
  pattern: Size,
  viewer: Size,
  dx: number,
  dy: number,
): Viewport {
  return clampViewport(
    { scale: vp.scale, x: vp.x + finite(dx), y: vp.y + finite(dy) },
    pattern,
    viewer,
  );
}

/**
 * The zoom factor of a wheel step: above 1 when scrolling up; opposite deltas cancel. A
 * huge delta still gives a finite factor, which the zoom then clamps.
 */
export function wheelFactor(deltaY: number): number {
  const exponent = -finite(deltaY) * WHEEL_RATE;
  return Math.exp(Math.max(-WHEEL_EXPONENT_MAX, Math.min(WHEEL_EXPONENT_MAX, exponent)));
}

/** The zoom factor of a pinch whose fingers went from one distance apart to another. */
export function pinchFactor(fromDistance: number, toDistance: number): number {
  if (!(fromDistance > 0)) {
    return 1;
  }
  return finite(toDistance / fromDistance, 1);
}

/**
 * The viewer changed size: the pattern point at the old centre goes to the new centre and
 * the scale is kept, unless the new fit is larger, which then applies, centred.
 */
export function resizeViewer(vp: Viewport, pattern: Size, from: Size, to: Size): Viewport {
  const fit = fitScale(pattern, to);
  if (!(vp.scale > 0) || fit >= vp.scale || fit === 0) {
    return fitViewport(pattern, to);
  }
  const scale = Math.min(vp.scale, maxScale(pattern, to));
  const centreX = (from.width / 2 - vp.x) / vp.scale;
  const centreY = (from.height / 2 - vp.y) / vp.scale;
  return clampViewport(
    { scale, x: to.width / 2 - centreX * scale, y: to.height / 2 - centreY * scale },
    pattern,
    to,
  );
}

const NOTHING: View = { firstColumn: 0, firstRow: 0, columns: 0, rows: 0 };

/** One axis of the window: the first cell partly in view and how many are. */
function windowAxis(position: number, scale: number, viewerPx: number, cells: number) {
  const first = Math.max(0, Math.floor(-position / scale));
  const end = Math.min(cells, Math.ceil((viewerPx - position) / scale));
  return { first: Math.min(first, cells), count: Math.max(0, end - first) };
}

/** The cells partly or wholly in view, clipped to the grid. */
export function visibleWindow(vp: Viewport, pattern: Size, viewer: Size): View {
  if (!(vp.scale > 0) || isEmpty(viewer) || isEmpty(pattern)) {
    return NOTHING;
  }
  const columns = windowAxis(vp.x, vp.scale, viewer.width, pattern.width);
  const rows = windowAxis(vp.y, vp.scale, viewer.height, pattern.height);
  if (columns.count === 0 || rows.count === 0) {
    return NOTHING;
  }
  return {
    firstColumn: columns.first,
    firstRow: rows.first,
    columns: columns.count,
    rows: rows.count,
  };
}
