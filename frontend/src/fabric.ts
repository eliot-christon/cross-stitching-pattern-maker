/**
 * Fabric shades to stitch on: common Aida colours, as screen approximations (fabric makers
 * publish names, not RGB values). Bare fabric in the viewer and the PDF thumbnails takes
 * the one chosen.
 */
export const FABRICS = [
  { name: "White", colour: "#ffffff" },
  { name: "Antique white", colour: "#f6efe1" },
  { name: "Ivory", colour: "#efe4c8" },
  { name: "Oatmeal", colour: "#d8c9ad" },
  { name: "Sky blue", colour: "#cddfee" },
  { name: "Rose", colour: "#f1d5da" },
  { name: "Grey", colour: "#a7a7a3" },
  { name: "Black", colour: "#1e1e1e" },
] as const;

/** The fabric a chart starts on: white, as the PDF assumes unless told otherwise. */
export const DEFAULT_FABRIC: string = FABRICS[0].colour;
