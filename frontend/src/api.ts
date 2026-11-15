import type { Pattern } from "./pattern";

/** The conversion endpoint, on the page's own origin; the Vite dev server proxies it. */
export const PATTERNS_URL = "/api/patterns";

/** What the API's tunable inputs accept: `GET /limits`, through the same proxy. */
export const LIMITS_URL = "/api/limits";

/** One tunable setting: `min` to `max` inclusive, a slider `step`, and where to start. */
export interface SettingLimits {
  min: number;
  max: number;
  step: number;
  default: number;
}

/** The `GET /limits` body, written by hand to match `LimitsOut` in src/cross_stitch/api/app.py. */
export interface Limits {
  /**
   * Largest accepted upload. Checked here too because the API refuses an oversized body
   * before reading it, and through a proxy that refusal arrives as a bare 502.
   */
  max_upload_bytes: number;
  /** Keyed by form field name: the conversion settings, then the PDF's layout settings. */
  settings: Record<
    | "width"
    | "max_colours"
    | "merge_distance"
    | "min_stitches"
    | "confetti_size"
    | "pages_across"
    | "pages_down"
    | "overlap",
    SettingLimits
  >;
}

export type LimitsResult = { ok: true; limits: Limits } | { ok: false; message: string };

/** The settings as the user typed them; the API validates them. */
export interface Settings {
  width: string;
  maxColours: string;
  fabricCount: string;
  /** Merge threads closer than this (CIEDE2000); "0" is off. */
  mergeDistance: string;
  /** Fold threads with fewer stitches into their nearest kept thread; "0" is off. */
  minStitches: string;
  /** Merge clusters of one thread up to this many cells into their surroundings; "0" is off. */
  confettiSize: string;
  /** Reduce the image to one pixel per art pixel before converting it. */
  pixelArt: boolean;
}

/** The image inspection endpoint: is the image pixel art, and of what size. */
export const INSPECT_URL = "/api/images/inspect";

/** An image's art pixels, as `POST /images/inspect` finds them. */
export interface PixelArt {
  width: number;
  height: number;
  colours: number;
}

export type InspectResult = { ok: true; pixelArt: PixelArt | null } | { ok: false; message: string };

/** The PDF chart endpoint: the same inputs as `PATTERNS_URL` plus the chart options. */
export const PATTERN_PDF_URL = "/api/patterns/pdf";

/** One thread swap, applied by the API after cleanup; a list applies in order. A `to` of
 * `null` removes the thread: its cells become bare fabric. */
export interface Replacement {
  from: DmcThread;
  to: DmcThread | null;
}

/** The `TO` of a `replace` field that removes a thread, as the API spells it. */
export const FABRIC = "fabric";

/** A replacement as the API's `replace` field spells it: `FROM:TO`. */
export function replacementField({ from, to }: Replacement): string {
  return `${from.code}:${to === null ? FABRIC : to.code}`;
}

/** The chart options `POST /patterns/pdf` accepts, as its form fields spell them. */
export interface ChartOptions {
  variant: "colour" | "bw";
  paper: "A2" | "A3" | "A4" | "A5";
  orientation: "portrait" | "landscape";
  /** "cells": a 3 mm cell, as many pages as needed; "pages": exactly across x down. */
  split: "cells" | "pages";
  /** Pages across and down in a "pages" split, as typed. */
  pagesAcross: string;
  pagesDown: string;
  /** Rows and columns neighbouring pages repeat, as typed. */
  overlap: string;
  centreLines: boolean;
  /** The fabric's colour, `#rrggbb`: bare cells in the PDF's thumbnails. */
  fabricColour: string;
}

/** The form fields of `POST /patterns/pdf` for these options. */
function chartFields(options: ChartOptions): Record<string, string> {
  return {
    variant: options.variant,
    paper: options.paper,
    orientation: options.orientation,
    split: options.split,
    pages_across: options.pagesAcross,
    pages_down: options.pagesDown,
    overlap: options.overlap,
    centre_lines: options.centreLines ? "true" : "false",
    fabric_colour: options.fabricColour,
  };
}

export type ConvertResult = { ok: true; pattern: Pattern } | { ok: false; message: string };

export type PdfResult = { ok: true; pdf: Blob } | { ok: false; message: string };

type Sent = { ok: true; response: Response } | { ok: false; message: string };

const UNREACHABLE = "Cannot reach the server. Is the API running?";
const MEGABYTE = 1024 * 1024;

/** A byte count as people read it: whole megabytes when it is some, bytes otherwise. */
function formatBytes(bytes: number): string {
  return bytes >= MEGABYTE ? `${Math.round((bytes / MEGABYTE) * 10) / 10} MB` : `${bytes} bytes`;
}

/** The limits the API reports for its tunable settings and the upload. */
export async function getLimits(): Promise<LimitsResult> {
  let response: Response;
  try {
    response = await fetch(LIMITS_URL);
  } catch {
    return { ok: false, message: UNREACHABLE };
  }
  const payload = await readJson(response);
  if (response.ok && payload !== undefined) {
    return { ok: true, limits: payload as Limits };
  }
  return {
    ok: false,
    message: errorMessage(response.status, payload, "Loading the settings failed"),
  };
}

/**
 * Post the image with `fill`'s fields, after the client-side size check against
 * `maxUploadBytes`, the API's reported limit.
 */
async function sendForm(
  url: string,
  image: File,
  maxUploadBytes: number,
  fill: (body: FormData) => void = () => {},
): Promise<Sent> {
  if (image.size > maxUploadBytes) {
    const limit = formatBytes(maxUploadBytes);
    return { ok: false, message: `The image is larger than ${limit}, the most the server accepts.` };
  }
  const body = new FormData();
  body.append("image", image);
  fill(body);
  try {
    return { ok: true, response: await fetch(url, { method: "POST", body }) };
  } catch {
    return { ok: false, message: UNREACHABLE };
  }
}

/** Post the image and settings (and any extra fields) to a pattern route. */
function post(
  url: string,
  image: File,
  settings: Settings,
  maxUploadBytes: number,
  replacements: readonly Replacement[],
  extra: Record<string, string> = {},
): Promise<Sent> {
  return sendForm(url, image, maxUploadBytes, (body) => appendSettings(body, settings, replacements, extra));
}

function appendSettings(
  body: FormData,
  settings: Settings,
  replacements: readonly Replacement[],
  extra: Record<string, string>,
) {
  body.append("width", settings.width);
  body.append("max_colours", settings.maxColours);
  body.append("fabric_count", settings.fabricCount);
  body.append("merge_distance", settings.mergeDistance);
  body.append("min_stitches", settings.minStitches);
  body.append("confetti_size", settings.confettiSize);
  body.append("pixel_art", settings.pixelArt ? "true" : "false");
  // Repeated `replace` fields, in order: the API applies them in sequence.
  for (const pair of replacements) {
    body.append("replace", replacementField(pair));
  }
  for (const [name, value] of Object.entries(extra)) {
    body.append(name, value);
  }
}

/** Whether the image is pixel art, and its size in art pixels and colours. */
export async function inspectImage(image: File, maxUploadBytes: number): Promise<InspectResult> {
  const sent = await sendForm(INSPECT_URL, image, maxUploadBytes);
  if (!sent.ok) {
    return sent;
  }
  const payload = await readJson(sent.response);
  if (sent.response.ok && typeof payload === "object" && payload !== null) {
    return { ok: true, pixelArt: (payload as { pixel_art?: PixelArt | null }).pixel_art ?? null };
  }
  return { ok: false, message: errorMessage(sent.response.status, payload, "Inspecting the image failed") };
}

/** The JSON body of a response, or `undefined` when it has none. */
async function readJson(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch {
    return undefined;
  }
}

/** The PDF chart of the image converted with `settings`, as the API renders it. */
export async function downloadPdf(
  image: File,
  settings: Settings,
  options: ChartOptions,
  maxUploadBytes: number,
  replacements: readonly Replacement[] = [],
): Promise<PdfResult> {
  const sent = await post(
    PATTERN_PDF_URL,
    image,
    settings,
    maxUploadBytes,
    replacements,
    chartFields(options),
  );
  if (!sent.ok) {
    return sent;
  }
  const { response } = sent;
  if (response.ok) {
    return { ok: true, pdf: await response.blob() };
  }
  return { ok: false, message: errorMessage(response.status, await readJson(response)) };
}

export async function convertImage(
  image: File,
  settings: Settings,
  maxUploadBytes: number,
  replacements: readonly Replacement[] = [],
): Promise<ConvertResult> {
  const sent = await post(PATTERNS_URL, image, settings, maxUploadBytes, replacements);
  if (!sent.ok) {
    return sent;
  }
  const { response } = sent;
  const payload = await readJson(response);
  if (response.ok && payload !== undefined) {
    return { ok: true, pattern: payload as Pattern };
  }
  return { ok: false, message: errorMessage(response.status, payload) };
}

interface ValidationError {
  loc: (string | number)[];
  msg: string;
}

function isValidationError(item: unknown): item is ValidationError {
  return (
    typeof item === "object" &&
    item !== null &&
    Array.isArray((item as ValidationError).loc) &&
    typeof (item as ValidationError).msg === "string"
  );
}

/**
 * The API's `detail`: a string, or FastAPI's list of `{loc, msg}`, each shown with its
 * field; `failed` and the status otherwise.
 */
function errorMessage(
  status: number,
  payload: unknown,
  failed = "The conversion failed",
): string {
  const detail =
    typeof payload === "object" && payload !== null
      ? (payload as { detail?: unknown }).detail
      : undefined;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0 && detail.every(isValidationError)) {
    return detail.map((error) => `${String(error.loc.at(-1))}: ${error.msg}`).join("; ");
  }
  return `${failed} (HTTP ${status}).`;
}

/** The DMC table, from `GET /threads`. */
export const THREADS_URL = "/api/threads";

/** A DMC thread as `GET /threads` gives it. */
export interface DmcThread {
  code: string;
  name: string;
  rgb: [number, number, number];
}

/** A thread near another, with the CIEDE2000 `distance` the API computed. */
export interface NearThread extends DmcThread {
  distance: number;
}

export type ThreadsResult<T> = { ok: true; threads: T[] } | { ok: false; message: string };

async function getList<T>(url: string, failed: string): Promise<ThreadsResult<T>> {
  let response: Response;
  try {
    response = await fetch(url);
  } catch {
    return { ok: false, message: UNREACHABLE };
  }
  const payload = await readJson(response);
  if (response.ok && Array.isArray(payload)) {
    return { ok: true, threads: payload as T[] };
  }
  return { ok: false, message: errorMessage(response.status, payload, failed) };
}

/** Every DMC thread, in the table's order. */
export function getThreads(): Promise<ThreadsResult<DmcThread>> {
  return getList<DmcThread>(THREADS_URL, "Loading the threads failed");
}

/** The threads nearest to `code`, nearest first, as the API ranks them. */
export function getNearestThreads(code: string): Promise<ThreadsResult<NearThread>> {
  return getList<NearThread>(
    `${THREADS_URL}/${encodeURIComponent(code)}/nearest`,
    "Loading the nearest threads failed",
  );
}

/** How the PDF would cut a pattern into pages: `POST /chart/layout`. */
export const CHART_LAYOUT_URL = "/api/chart/layout";

/** A run of columns or rows on one chart page. */
export interface Band {
  start: number;
  end: number;
  repeated: number;
}

/** The pages of a chart: the cell, the bands, and each section's name by row. */
export interface ChartLayout {
  cell_mm: number;
  columns: Band[];
  rows: Band[];
  sections: string[][];
}

/** One pages split: its cell (`null` where the PDF refuses it) and its biggest page. */
export interface PageOption {
  cell_mm: number | null;
  columns: number;
  rows: number;
}

/** The `POST /chart/layout` body, written by hand to match `ChartLayoutOut`. */
export interface ChartLayoutReport {
  layout: ChartLayout | null;
  message: string | null;
  /** Every pages split, `pages[down - 1][across - 1]`. */
  pages: PageOption[][];
}

export type ChartLayoutResult = { ok: true; report: ChartLayoutReport } | { ok: false; message: string };

/** How the PDF with `options` would cut a `width` x `height` pattern, and every split. */
export async function getChartLayout(
  width: number,
  height: number,
  options: ChartOptions,
): Promise<ChartLayoutResult> {
  const body = new FormData();
  body.append("width", String(width));
  body.append("height", String(height));
  for (const [name, value] of Object.entries(chartFields(options))) {
    body.append(name, value);
  }
  let response: Response;
  try {
    response = await fetch(CHART_LAYOUT_URL, { method: "POST", body });
  } catch {
    return { ok: false, message: UNREACHABLE };
  }
  const payload = await readJson(response);
  if (response.ok && typeof payload === "object" && payload !== null) {
    return { ok: true, report: payload as ChartLayoutReport };
  }
  return { ok: false, message: errorMessage(response.status, payload, "Loading the chart layout failed") };
}
