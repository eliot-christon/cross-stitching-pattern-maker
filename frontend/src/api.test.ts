import { afterEach, describe, expect, it, vi } from "vitest";

import {
  LIMITS_URL,
  PATTERN_PDF_URL,
  PATTERNS_URL,
  convertImage,
  downloadPdf,
  getLimits,
  type Limits,
} from "./api";
import type { Pattern } from "./pattern";

const SETTINGS = {
  width: "40",
  maxColours: "4",
  fabricCount: "16",
  mergeDistance: "2.5",
  minStitches: "10",
  confettiSize: "1",
};

/** An upload limit as the API reports it today; the size checks take it as an argument. */
const LIMIT = 20 * 1024 * 1024;

const PATTERN: Pattern = {
  width: 2,
  height: 1,
  fabric_count: 16,
  grid: [[0, null]],
  key: [{ code: "310", name: "Black", rgb: [0, 0, 0], stitches: 1, skeins: 1, symbol: "A" }],
  total_stitches: 1,
  finished_size: { width_in: 0.125, height_in: 0.0625, width_cm: 0.3175, height_cm: 0.15875 },
  isolated_stitches: { before: 1, after: 1 },
};

function image(size?: number): File {
  const file = new File(["png bytes"], "photo.png", { type: "image/png" });
  if (size !== undefined) {
    Object.defineProperty(file, "size", { value: size });
  }
  return file;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch(response: Response | Error) {
  const fetchMock = vi.fn(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("convertImage", () => {
  it("posts the file and the settings exactly as entered to the conversion URL", async () => {
    const fetchMock = stubFetch(json(200, PATTERN));
    const file = image();

    await convertImage(file, SETTINGS, LIMIT);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(PATTERNS_URL);
    expect(PATTERNS_URL).toBe("/api/patterns");
    expect(init.method).toBe("POST");
    const body = init.body as FormData;
    const posted = body.get("image") as File;
    expect(posted.name).toBe("photo.png");
    expect(posted.size).toBe(file.size);
    expect(body.get("width")).toBe("40");
    expect(body.get("max_colours")).toBe("4");
    expect(body.get("fabric_count")).toBe("16");
    expect(body.get("merge_distance")).toBe("2.5");
    expect(body.get("min_stitches")).toBe("10");
    expect(body.get("confetti_size")).toBe("1");
  });

  it("returns the pattern from a 200", async () => {
    stubFetch(json(200, PATTERN));

    expect(await convertImage(image(), SETTINGS, LIMIT)).toEqual({ ok: true, pattern: PATTERN });
  });

  it("sends out-of-range settings anyway: the API decides", async () => {
    const fetchMock = stubFetch(json(200, PATTERN));

    await convertImage(image(), { ...SETTINGS, width: "0" }, LIMIT);

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.body as FormData).get("width")).toBe("0");
  });

  it.each([
    [400, "the upload is not a decodable image"],
    [413, "the upload is larger than 20971520 bytes"],
    [422, "height would be 1001 stitches at width 1; at most 1000"],
  ])("shows the API's string detail for a %i", async (status, detail) => {
    stubFetch(json(status, { detail }));

    expect(await convertImage(image(), SETTINGS, LIMIT)).toEqual({ ok: false, message: detail });
  });

  it("names the field of a validation 422", async () => {
    stubFetch(
      json(422, {
        detail: [
          { loc: ["body", "width"], msg: "Input should be less than or equal to 1000" },
        ],
      }),
    );

    const result = await convertImage(image(), SETTINGS, LIMIT);

    expect(result.ok).toBe(false);
    const { message } = result as { message: string };
    expect(message).toContain("width");
    expect(message).toContain("Input should be less than or equal to 1000");
  });

  it("joins several validation errors", async () => {
    stubFetch(
      json(422, {
        detail: [
          { loc: ["body", "width"], msg: "Input should be greater than or equal to 1" },
          { loc: ["body", "max_colours"], msg: "Input should be a valid integer" },
        ],
      }),
    );

    const { message } = (await convertImage(image(), SETTINGS, LIMIT)) as { message: string };

    expect(message).toContain("width: Input should be greater than or equal to 1");
    expect(message).toContain("max_colours: Input should be a valid integer");
  });

  it("gives a generic message for a 500 with an HTML body", async () => {
    stubFetch(new Response("<html>Internal Server Error</html>", { status: 500 }));

    const result = await convertImage(image(), SETTINGS, LIMIT);

    expect(result).toEqual({ ok: false, message: expect.stringContaining("500") });
  });

  it("gives a generic message for a 502 with an empty body", async () => {
    stubFetch(new Response(null, { status: 502 }));

    const result = await convertImage(image(), SETTINGS, LIMIT);

    expect(result).toEqual({ ok: false, message: expect.stringContaining("502") });
  });

  it("gives a generic message for a 200 that is not JSON", async () => {
    stubFetch(new Response("not json", { status: 200 }));

    const result = await convertImage(image(), SETTINGS, LIMIT);

    expect(result.ok).toBe(false);
  });

  it("says the server cannot be reached when fetch rejects", async () => {
    stubFetch(new TypeError("Failed to fetch"));

    const { message } = (await convertImage(image(), SETTINGS, LIMIT)) as { message: string };

    expect(message).toMatch(/cannot reach the server/i);
  });

  it("refuses a file one byte over the limit without any request", async () => {
    const fetchMock = stubFetch(json(200, PATTERN));

    const result = await convertImage(image(LIMIT + 1), SETTINGS, LIMIT);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result).toEqual({ ok: false, message: expect.stringContaining("20 MB") });
  });

  it("posts a file of exactly the limit", async () => {
    const fetchMock = stubFetch(json(200, PATTERN));

    await convertImage(image(LIMIT), SETTINGS, LIMIT);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("checks the size against the limit it is given", async () => {
    const fetchMock = stubFetch(json(200, PATTERN));

    const result = await convertImage(image(1001), SETTINGS, 1000);

    expect(result).toEqual({
      ok: false,
      message: "The image is larger than 1000 bytes, the most the server accepts.",
    });
    expect(fetchMock).not.toHaveBeenCalled();
    await convertImage(image(1000), SETTINGS, 1000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("getLimits", () => {
  const LIMITS: Limits = {
    max_upload_bytes: 1000,
    settings: {
      width: { min: 1, max: 500, step: 1, default: 100 },
      max_colours: { min: 1, max: 100, step: 1, default: 7 },
      merge_distance: { min: 0, max: 10, step: 0.5, default: 0 },
      min_stitches: { min: 0, max: 1000, step: 1, default: 0 },
      confetti_size: { min: 0, max: 10, step: 1, default: 0 },
    },
  };

  it("gets the limits from the limits URL and returns them as sent", async () => {
    const fetchMock = stubFetch(json(200, LIMITS));

    expect(await getLimits()).toEqual({ ok: true, limits: LIMITS });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit | undefined];
    expect(url).toBe(LIMITS_URL);
    expect(LIMITS_URL).toBe("/api/limits");
    expect(init?.method ?? "GET").toBe("GET");
  });

  it("fails with a message on a 500", async () => {
    stubFetch(new Response("<html>oops</html>", { status: 500 }));

    expect(await getLimits()).toEqual({
      ok: false,
      message: "Loading the settings failed (HTTP 500).",
    });
  });

  it("fails with the API's message when it gives one", async () => {
    stubFetch(json(503, { detail: "starting up" }));

    expect(await getLimits()).toEqual({ ok: false, message: "starting up" });
  });

  it("says the server cannot be reached when fetch rejects", async () => {
    stubFetch(new TypeError("Failed to fetch"));

    expect(await getLimits()).toEqual({
      ok: false,
      message: "Cannot reach the server. Is the API running?",
    });
  });
});

describe("downloadPdf", () => {
  const OPTIONS = { variant: "bw", paper: "A3", orientation: "landscape" } as const;

  function pdf(): Response {
    // A string body: jsdom's Blob is not the one Node's Response reads.
    return new Response("%PDF-1.4 chart", {
      status: 200,
      headers: { "Content-Type": "application/pdf" },
    });
  }

  it("posts the file, the settings and the chart options to the PDF URL", async () => {
    const fetchMock = stubFetch(pdf());
    const file = image();

    await downloadPdf(file, { ...SETTINGS, fabricCount: "14" }, OPTIONS, LIMIT);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(PATTERN_PDF_URL);
    expect(PATTERN_PDF_URL).toBe("/api/patterns/pdf");
    expect(init.method).toBe("POST");
    const body = init.body as FormData;
    expect(body.get("image")).toBe(file);
    expect(body.get("width")).toBe("40");
    expect(body.get("max_colours")).toBe("4");
    expect(body.get("fabric_count")).toBe("14");
    expect(body.get("merge_distance")).toBe("2.5");
    expect(body.get("min_stitches")).toBe("10");
    expect(body.get("confetti_size")).toBe("1");
    expect(body.get("variant")).toBe("bw");
    expect(body.get("paper")).toBe("A3");
    expect(body.get("orientation")).toBe("landscape");
  });

  it("returns the PDF bytes of a 200", async () => {
    stubFetch(pdf());

    const result = await downloadPdf(image(), SETTINGS, OPTIONS, LIMIT);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(await result.pdf.text()).toBe("%PDF-1.4 chart");
    }
  });

  it("names the field of a validation 422", async () => {
    stubFetch(json(422, { detail: [{ loc: ["body", "width"], msg: "too big" }] }));

    expect(await downloadPdf(image(), SETTINGS, OPTIONS, LIMIT)).toEqual({
      ok: false,
      message: "width: too big",
    });
  });

  it("shows a string detail as is", async () => {
    stubFetch(json(400, { detail: "the upload is not a decodable image" }));

    expect(await downloadPdf(image(), SETTINGS, OPTIONS, LIMIT)).toEqual({
      ok: false,
      message: "the upload is not a decodable image",
    });
  });

  it("refuses a file over the limit without any request", async () => {
    const fetchMock = stubFetch(pdf());

    const result = await downloadPdf(image(LIMIT + 1), SETTINGS, OPTIONS, LIMIT);

    expect(result).toEqual({
      ok: false,
      message: "The image is larger than 20 MB, the most the server accepts.",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says the server cannot be reached when fetch rejects", async () => {
    stubFetch(new TypeError("Failed to fetch"));

    expect(await downloadPdf(image(), SETTINGS, OPTIONS, LIMIT)).toEqual({
      ok: false,
      message: "Cannot reach the server. Is the API running?",
    });
  });
});
