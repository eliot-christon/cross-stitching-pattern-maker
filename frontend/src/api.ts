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
  /** Keyed by the form field name of `POST /patterns`. */
  settings: Record<
    "width" | "max_colours" | "merge_distance" | "min_stitches" | "confetti_size",
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
}

/** The PDF chart endpoint: the same inputs as `PATTERNS_URL` plus the chart options. */
export const PATTERN_PDF_URL = "/api/patterns/pdf";

/** The chart options `POST /patterns/pdf` accepts, as its form fields spell them. */
export interface ChartOptions {
  variant: "colour" | "bw";
  paper: "A2" | "A3" | "A4" | "A5";
  orientation: "portrait" | "landscape";
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
 * Post the image and settings (and any extra fields), after the client-side size check
 * against `maxUploadBytes`, the API's reported limit.
 */
async function post(
  url: string,
  image: File,
  settings: Settings,
  maxUploadBytes: number,
  extra: Record<string, string> = {},
): Promise<Sent> {
  if (image.size > maxUploadBytes) {
    const limit = formatBytes(maxUploadBytes);
    return { ok: false, message: `The image is larger than ${limit}, the most the server accepts.` };
  }

  const body = new FormData();
  body.append("image", image);
  body.append("width", settings.width);
  body.append("max_colours", settings.maxColours);
  body.append("fabric_count", settings.fabricCount);
  body.append("merge_distance", settings.mergeDistance);
  body.append("min_stitches", settings.minStitches);
  body.append("confetti_size", settings.confettiSize);
  for (const [name, value] of Object.entries(extra)) {
    body.append(name, value);
  }

  try {
    return { ok: true, response: await fetch(url, { method: "POST", body }) };
  } catch {
    return { ok: false, message: UNREACHABLE };
  }
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
): Promise<PdfResult> {
  const sent = await post(PATTERN_PDF_URL, image, settings, maxUploadBytes, { ...options });
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
): Promise<ConvertResult> {
  const sent = await post(PATTERNS_URL, image, settings, maxUploadBytes);
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
