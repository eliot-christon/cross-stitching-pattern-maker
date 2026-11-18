import { afterEach, describe, expect, it, vi } from "vitest";

import {
  LIMITS_URL,
  PATTERN_PDF_URL,
  PATTERNS_URL,
  convertImage,
  downloadPdf,
  getChartLayout,
  getLimits,
  getNearestThreads,
  getThreads,
  inspectImage,
  type Change,
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
  readAs: "picture",
  crop: "",
  backgroundAsFabric: false,
  brightness: "0",
  contrast: "0",
  saturation: "0",
  hue: "0",
  gamma: "1",
  sharpness: "0",
};

/** An upload limit as the API reports it today; the size checks take it as an argument. */
const LIMIT = 20 * 1024 * 1024;

const PATTERN: Pattern = {
  width: 2,
  height: 1,
  fabric_count: 16,
  grid: [[0, null]],
  key: [{ code: "310", name: "Black", rgb: [0, 0, 0], stitches: 1, skeins: 1, symbol: "A", symbol_ink: "white" }],
  total_stitches: 1,
  finished_size: { width_in: 0.125, height_in: 0.0625, width_cm: 0.3175, height_cm: 0.15875 },
  isolated_stitches: { before: 1, after: 1 },
  converted: null,
  changed_cells: [],
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
    expect(body.get("read_as")).toBe("picture");
    expect(body.get("background_as_fabric")).toBe("false");
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
      brightness: { min: -100, max: 100, step: 1, default: 0 },
      contrast: { min: -100, max: 100, step: 1, default: 0 },
      saturation: { min: -100, max: 100, step: 1, default: 0 },
      hue: { min: -180, max: 180, step: 1, default: 0 },
      gamma: { min: 0.25, max: 4, step: 0.05, default: 1 },
      sharpness: { min: -100, max: 100, step: 1, default: 0 },
      pages_across: { min: 1, max: 20, step: 1, default: 2 },
      pages_down: { min: 1, max: 20, step: 1, default: 2 },
      overlap: { min: 0, max: 5, step: 1, default: 2 },
    },
    changes: { max_entries: 1000, max_bytes: 524288, brush: { min: 1, max: 9, step: 2, default: 1 }, max_coordinate: 2000 },
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
  const OPTIONS = {
    variant: "bw",
    paper: "A3",
    orientation: "landscape",
    split: "cells",
    pagesAcross: "2",
    pagesDown: "2",
    overlap: "2",
    centreLines: false,
    fabricColour: "#f6efe1",
  } as const;

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

describe("thread table and nearest threads", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function stubFetch(response: Response | Error) {
    const fetchMock = vi.fn((_url: string) =>
      response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
    );
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  function jsonResponse(status: number, body: unknown): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  it("asks /api/threads for the table and returns the list", async () => {
    const table = [{ code: "310", name: "Black", rgb: [0, 0, 0] }];
    const fetchMock = stubFetch(jsonResponse(200, table));

    const result = await getThreads();

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/threads");
    expect(result).toEqual({ ok: true, threads: table });
  });

  it("asks for a code's nearest threads, encoding the code", async () => {
    const fetchMock = stubFetch(jsonResponse(200, []));
    await getNearestThreads("B5200");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/threads/B5200/nearest");

    const second = stubFetch(jsonResponse(200, []));
    await getNearestThreads("a/b c");
    expect(second.mock.calls[0]?.[0]).toBe("/api/threads/a%2Fb%20c/nearest");
  });

  it("gives the API's message for an unknown code, and the unreachable one offline", async () => {
    stubFetch(jsonResponse(404, { detail: "unknown DMC code: 'XYZ'" }));
    expect(await getNearestThreads("XYZ")).toEqual({
      ok: false,
      message: "unknown DMC code: 'XYZ'",
    });

    stubFetch(new TypeError("offline"));
    const offline = await getThreads();
    expect(offline.ok).toBe(false);
    expect(offline.ok ? "" : offline.message).toMatch(/cannot reach the server/i);
  });
});

describe("changes on the wire", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const settings = {
    width: "40",
    maxColours: "4",
    fabricCount: "14",
    mergeDistance: "0",
    minStitches: "0",
    confettiSize: "0",
    readAs: "picture",
    crop: "",
    backgroundAsFabric: false,
    brightness: "0",
    contrast: "0",
    saturation: "0",
    hue: "0",
    gamma: "1",
    sharpness: "0",
  };
  const chart = {
    variant: "colour",
    paper: "A4",
    orientation: "portrait",
    split: "cells",
    pagesAcross: "2",
    pagesDown: "2",
    overlap: "2",
    centreLines: false,
    fabricColour: "#ffffff",
  } as const;
  const black = { code: "310", name: "Black", rgb: [0, 0, 0] as [number, number, number] };
  const winter = { code: "3865", name: "Winter White", rgb: [249, 247, 241] as [number, number, number] };
  const red = { code: "321", name: "Red", rgb: [199, 43, 59] as [number, number, number] };
  const image = new File(["x"], "a.png", { type: "image/png" });

  function capture() {
    const bodies: FormData[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        bodies.push(init?.body as FormData);
        return Promise.resolve(new Response("{}", { status: 500 }));
      }),
    );
    return bodies;
  }

  function sentChanges(body: FormData | undefined): unknown {
    const field = body?.get("changes");
    return typeof field === "string" ? JSON.parse(field) : field;
  }

  it("sends a replacement and a removal as one changes field, and no replace field", async () => {
    const bodies = capture();
    const changes: Change[] = [
      { op: "replace", from: black, to: winter },
      { op: "replace", from: red, to: null },
    ];

    await convertImage(image, settings, 1000, changes);

    expect(bodies[0]?.getAll("changes")).toEqual([
      '[{"op":"replace","from":"310","to":"3865"},{"op":"replace","from":"321","to":null}]',
    ]);
    expect(bodies[0]?.has("replace")).toBe(false);
  });

  it("spells a stroke, a rectangle and an eraser fill as the API reads them", async () => {
    const bodies = capture();
    const changes: Change[] = [
      { op: "stroke", thread: black, brush: 3, grid: [40, 20], points: [[1, 2], [3, 2]] },
      { op: "rect", thread: winter, grid: [40, 20], from: [5, 6], to: [1, 0] },
      { op: "fill", thread: null, grid: [40, 20], at: [7, 8] },
    ];

    await convertImage(image, settings, 1000, changes);

    expect(sentChanges(bodies[0])).toEqual([
      { op: "stroke", thread: "310", brush: 3, grid: [40, 20], points: [[1, 2], [3, 2]] },
      { op: "rect", thread: "3865", grid: [40, 20], from: [5, 6], to: [1, 0] },
      { op: "fill", thread: null, grid: [40, 20], at: [7, 8] },
    ]);
  });

  it("sends no changes field for an empty list, and the same field on both routes", async () => {
    const bodies = capture();
    const changes: Change[] = [{ op: "replace", from: black, to: winter }];

    await convertImage(image, settings, 1000, []);
    await convertImage(image, settings, 1000, changes);
    await downloadPdf(image, settings, chart, 1000, changes);

    expect(bodies[0]?.has("changes")).toBe(false);
    expect(bodies[2]?.get("changes")).toBe(bodies[1]?.get("changes"));
  });
});

describe("adjustments on the wire", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const adjustments = { brightness: "12", contrast: "-5", saturation: "abc", hue: "180", gamma: "0.5", sharpness: "" };
  const settings = {
    width: "40",
    maxColours: "4",
    fabricCount: "14",
    mergeDistance: "0",
    minStitches: "0",
    confettiSize: "0",
    readAs: "picture",
    crop: "",
    backgroundAsFabric: false,
    ...adjustments,
  };
  const chart = {
    variant: "colour",
    paper: "A4",
    orientation: "portrait",
    split: "cells",
    pagesAcross: "2",
    pagesDown: "2",
    overlap: "2",
    centreLines: false,
    fabricColour: "#ffffff",
  } as const;

  it("sends the six adjustments as typed with the inspection, the conversion and the PDF", async () => {
    const bodies: FormData[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        bodies.push(init?.body as FormData);
        return Promise.resolve(new Response("{}", { status: 500 }));
      }),
    );
    const image = new File(["x"], "a.png", { type: "image/png" });

    await inspectImage(image, 1000, "", adjustments);
    await convertImage(image, settings, 1000);
    await downloadPdf(image, settings, chart, 1000);

    for (const body of bodies) {
      expect(Object.fromEntries(Object.keys(adjustments).map((field) => [field, body.get(field)]))).toEqual(adjustments);
    }
    expect(bodies).toHaveLength(3);
  });

  it("sends no adjustment with an inspection given none", async () => {
    const bodies: FormData[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        bodies.push(init?.body as FormData);
        return Promise.resolve(new Response("{}", { status: 500 }));
      }),
    );

    await inspectImage(new File(["x"], "a.png", { type: "image/png" }), 1000);

    expect(bodies[0]?.has("brightness")).toBe(false);
  });
});

describe("chart layout on the wire", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const settings = {
    width: "40",
    maxColours: "4",
    fabricCount: "14",
    mergeDistance: "0",
    minStitches: "0",
    confettiSize: "0",
    readAs: "picture",
    crop: "",
    backgroundAsFabric: false,
    brightness: "0",
    contrast: "0",
    saturation: "0",
    hue: "0",
    gamma: "1",
    sharpness: "0",
  };
  const layoutFields = ["split", "pages_across", "pages_down", "overlap", "centre_lines"];

  function capture() {
    const bodies: FormData[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        bodies.push(init?.body as FormData);
        return Promise.resolve(new Response("{}", { status: 500 }));
      }),
    );
    return bodies;
  }

  it("sends the layout choices with the PDF request, and none with the conversion", async () => {
    const bodies = capture();
    const image = new File(["x"], "a.png", { type: "image/png" });
    const options = {
      variant: "colour",
      paper: "A4",
      orientation: "portrait",
      split: "pages",
      pagesAcross: "3",
      pagesDown: "2",
      overlap: "0",
      centreLines: true,
      fabricColour: "#1e1e1e",
    } as const;

    await downloadPdf(image, settings, options, 1000);
    await convertImage(image, settings, 1000);

    const [pdfBody, conversion] = bodies;
    expect(layoutFields.map((name) => pdfBody?.get(name))).toEqual(["pages", "3", "2", "0", "true"]);
    expect(pdfBody?.get("variant")).toBe("colour");
    expect(pdfBody?.get("fabric_colour")).toBe("#1e1e1e");
    expect(layoutFields.map((name) => conversion?.get(name))).toEqual([null, null, null, null, null]);
    expect(conversion?.get("fabric_colour")).toBeNull();
  });
});

describe("inspectImage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const FOUND = {
    kind: "pixel_art",
    description: "Pixel art, 64 x 60 stitches, 6 colours",
    grid: { width: 64, height: 60, colours: 6 },
    warnings: [],
    refusal: null,
  };

  it("posts the image alone and gives what the inspection found", async () => {
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response(JSON.stringify(FOUND))),
    );
    vi.stubGlobal("fetch", fetchMock);
    const image = new File(["x"], "a.png", { type: "image/png" });

    const result = await inspectImage(image, 1000);

    expect(result).toEqual({ ok: true, inspection: FOUND });
    const call = fetchMock.mock.calls[0];
    expect(call?.[0]).toBe("/api/images/inspect");
    const body = call?.[1]?.body as FormData;
    expect([...body.keys()]).toEqual(["image"]);
  });

  it("gives a refusal as found, and the API's message on failure", async () => {
    const refused = { ...FOUND, kind: null, description: "PDF document", grid: null, refusal: "no PDF" };
    const answers = [
      new Response(JSON.stringify(refused)),
      new Response(JSON.stringify({ detail: "the upload is not a decodable image" }), { status: 400 }),
    ];
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(answers.shift() as Response)));
    const image = new File(["x"], "a.png", { type: "image/png" });

    expect(await inspectImage(image, 1000)).toEqual({ ok: true, inspection: refused });
    expect(await inspectImage(image, 1000)).toEqual({
      ok: false,
      message: "the upload is not a decodable image",
    });
  });
});

describe("getChartLayout", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the size and chart choices and gives the API's report", async () => {
    const report = { layout: null, message: "too small", pages: [] };
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response(JSON.stringify(report))),
    );
    vi.stubGlobal("fetch", fetchMock);
    const options = {
      variant: "colour",
      paper: "A3",
      orientation: "landscape",
      split: "pages",
      pagesAcross: "3",
      pagesDown: "2",
      overlap: "1",
      centreLines: false,
      fabricColour: "#ffffff",
    } as const;

    expect(await getChartLayout(120, 80, options)).toEqual({ ok: true, report });
    const call = fetchMock.mock.calls[0];
    expect(call?.[0]).toBe("/api/chart/layout");
    const body = call?.[1]?.body as FormData;
    expect(["width", "height", "paper", "orientation", "split", "pages_across", "pages_down", "overlap"].map((n) => body.get(n))).toEqual(
      ["120", "80", "A3", "landscape", "pages", "3", "2", "1"],
    );
  });
});
