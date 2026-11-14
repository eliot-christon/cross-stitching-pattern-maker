import type { Pattern } from "./pattern";

/** The conversion endpoint, on the page's own origin; the Vite dev server proxies it. */
export const PATTERNS_URL = "/api/patterns";

/**
 * Largest accepted upload: `MAX_UPLOAD_BYTES` in src/cross_stitch/api/app.py, which stays
 * the authority. It is checked here too because the API refuses an oversized body before
 * reading it, and through a proxy that refusal arrives as a bare 502.
 */
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

/** The settings as the user typed them; the API validates them. */
export interface Settings {
  width: string;
  maxColours: string;
  fabricCount: string;
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

/** Post the image and settings (and any extra fields), after the client-side size check. */
async function post(
  url: string,
  image: File,
  settings: Settings,
  extra: Record<string, string> = {},
): Promise<Sent> {
  if (image.size > MAX_UPLOAD_BYTES) {
    const limit = `${MAX_UPLOAD_BYTES / (1024 * 1024)} MB`;
    return { ok: false, message: `The image is larger than ${limit}, the most the server accepts.` };
  }

  const body = new FormData();
  body.append("image", image);
  body.append("width", settings.width);
  body.append("max_colours", settings.maxColours);
  body.append("fabric_count", settings.fabricCount);
  for (const [name, value] of Object.entries(extra)) {
    body.append(name, value);
  }

  try {
    return { ok: true, response: await fetch(url, { method: "POST", body }) };
  } catch {
    return { ok: false, message: "Cannot reach the server. Is the API running?" };
  }
}

/** The PDF chart of the image converted with `settings`, as the API renders it. */
export async function downloadPdf(
  image: File,
  settings: Settings,
  options: ChartOptions,
): Promise<PdfResult> {
  const sent = await post(PATTERN_PDF_URL, image, settings, { ...options });
  if (!sent.ok) {
    return sent;
  }
  const { response } = sent;
  if (response.ok) {
    return { ok: true, pdf: await response.blob() };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = undefined;
  }
  return { ok: false, message: errorMessage(response.status, payload) };
}

export async function convertImage(image: File, settings: Settings): Promise<ConvertResult> {
  const sent = await post(PATTERNS_URL, image, settings);
  if (!sent.ok) {
    return sent;
  }
  const { response } = sent;

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = undefined;
  }

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

/** The API's `detail`: a string, or FastAPI's list of `{loc, msg}`, each shown with its field. */
function errorMessage(status: number, payload: unknown): string {
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
  return `The conversion failed (HTTP ${status}).`;
}
