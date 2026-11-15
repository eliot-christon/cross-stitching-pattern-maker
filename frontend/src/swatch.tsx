/** Colour swatches: a thread's colour exactly as the API gives it, or bare fabric. */

export type Rgb = readonly [number, number, number];

/** A colour as CSS reads it. */
export function rgbCss(rgb: Rgb): string {
  return `rgb(${rgb.join(", ")})`;
}

/** A thread's colour, decorative: the code and name next to it say which thread it is. */
export function Swatch({ rgb }: { rgb: Rgb }) {
  return <span aria-hidden="true" className="swatch" style={{ backgroundColor: rgbCss(rgb) }} />;
}

/** Bare fabric: no thread, drawn as an empty, hatched square. */
export function FabricSwatch() {
  return <span aria-hidden="true" className="swatch swatch-fabric" />;
}
