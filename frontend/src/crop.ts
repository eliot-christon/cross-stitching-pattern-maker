/** A crop box in pixels of the upright image: right and bottom excluded. */
export interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

function clamp(value: number, max: number): number {
  return Math.min(Math.max(value, 0), max);
}

/**
 * The box a drag from `start` to `end` draws, both in pixels of the image as `shown`, in
 * pixels of the image itself (`natural`): the drag is clamped to the shown image, either
 * direction draws the same box, and a drag under one image pixel either way is no box.
 */
export function boxFromDrag(start: Point, end: Point, shown: Size, natural: Size): Box | null {
  const scaleX = natural.width / shown.width;
  const scaleY = natural.height / shown.height;
  const [x0, x1] = [start.x, end.x].map((x) => clamp(x, shown.width) * scaleX).sort((a, b) => a - b);
  const [y0, y1] = [start.y, end.y].map((y) => clamp(y, shown.height) * scaleY).sort((a, b) => a - b);
  if (x0 === undefined || x1 === undefined || y0 === undefined || y1 === undefined) {
    return null;
  }
  if (x1 - x0 < 1 || y1 - y0 < 1) {
    return null;
  }
  return {
    left: Math.round(x0),
    top: Math.round(y0),
    right: Math.min(Math.round(x1), natural.width),
    bottom: Math.min(Math.round(y1), natural.height),
  };
}

/** The box in percent of the image's width and height, to draw it at any shown size. */
export function percentRect(box: Box, natural: Size): Box {
  return {
    left: (box.left / natural.width) * 100,
    top: (box.top / natural.height) * 100,
    right: (box.right / natural.width) * 100,
    bottom: (box.bottom / natural.height) * 100,
  };
}

/** The box as the API's `crop` field spells it: `left,top,right,bottom`. */
export function cropField(box: Box): string {
  return `${box.left},${box.top},${box.right},${box.bottom}`;
}

/** A `crop` field back as a box; null for "" (no crop) or anything else. */
export function boxFromField(field: string): Box | null {
  const parts = field.split(",").map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part))) {
    return null;
  }
  const [left = 0, top = 0, right = 0, bottom = 0] = parts;
  return { left, top, right, bottom };
}
