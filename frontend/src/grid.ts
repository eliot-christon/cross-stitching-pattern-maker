import type { Pattern } from "./pattern";

/**
 * One RGBA pixel per cell, row-major, ready for `ImageData`. A cell takes its key entry's
 * `rgb` unchanged and full alpha; a bare-fabric cell is fully transparent.
 */
export function gridPixels(
  pattern: Pick<Pattern, "width" | "height" | "grid" | "key">,
): Uint8ClampedArray<ArrayBuffer> {
  const { width, height, grid, key } = pattern;
  const pixels = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    const row = grid[y] ?? [];
    for (let x = 0; x < width; x++) {
      const index = row[x] ?? null;
      if (index === null) {
        continue;
      }
      const entry = key[index];
      if (entry === undefined) {
        throw new Error(`cell (${x}, ${y}) points at key entry ${index}, which does not exist`);
      }
      const offset = (y * width + x) * 4;
      pixels[offset] = entry.rgb[0];
      pixels[offset + 1] = entry.rgb[1];
      pixels[offset + 2] = entry.rgb[2];
      pixels[offset + 3] = 255;
    }
  }
  return pixels;
}
