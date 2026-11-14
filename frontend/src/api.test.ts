import { afterEach, describe, expect, it, vi } from "vitest";

import { MAX_UPLOAD_BYTES, PATTERNS_URL, convertImage } from "./api";
import type { Pattern } from "./pattern";

const SETTINGS = { width: "40", maxColours: "4", fabricCount: "16" };

const PATTERN: Pattern = {
  width: 2,
  height: 1,
  fabric_count: 16,
  grid: [[0, null]],
  key: [{ code: "310", name: "Black", rgb: [0, 0, 0], stitches: 1, skeins: 1, symbol: "A" }],
  total_stitches: 1,
  finished_size: { width_in: 0.125, height_in: 0.0625, width_cm: 0.3175, height_cm: 0.15875 },
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

    await convertImage(file, SETTINGS);

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
  });

  it("returns the pattern from a 200", async () => {
    stubFetch(json(200, PATTERN));

    expect(await convertImage(image(), SETTINGS)).toEqual({ ok: true, pattern: PATTERN });
  });

  it("sends out-of-range settings anyway: the API decides", async () => {
    const fetchMock = stubFetch(json(200, PATTERN));

    await convertImage(image(), { ...SETTINGS, width: "0" });

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.body as FormData).get("width")).toBe("0");
  });

  it.each([
    [400, "the upload is not a decodable image"],
    [413, "the upload is larger than 20971520 bytes"],
    [422, "height would be 1001 stitches at width 1; at most 1000"],
  ])("shows the API's string detail for a %i", async (status, detail) => {
    stubFetch(json(status, { detail }));

    expect(await convertImage(image(), SETTINGS)).toEqual({ ok: false, message: detail });
  });

  it("names the field of a validation 422", async () => {
    stubFetch(
      json(422, {
        detail: [
          { loc: ["body", "width"], msg: "Input should be less than or equal to 1000" },
        ],
      }),
    );

    const result = await convertImage(image(), SETTINGS);

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

    const { message } = (await convertImage(image(), SETTINGS)) as { message: string };

    expect(message).toContain("width: Input should be greater than or equal to 1");
    expect(message).toContain("max_colours: Input should be a valid integer");
  });

  it("gives a generic message for a 500 with an HTML body", async () => {
    stubFetch(new Response("<html>Internal Server Error</html>", { status: 500 }));

    const result = await convertImage(image(), SETTINGS);

    expect(result).toEqual({ ok: false, message: expect.stringContaining("500") });
  });

  it("gives a generic message for a 502 with an empty body", async () => {
    stubFetch(new Response(null, { status: 502 }));

    const result = await convertImage(image(), SETTINGS);

    expect(result).toEqual({ ok: false, message: expect.stringContaining("502") });
  });

  it("gives a generic message for a 200 that is not JSON", async () => {
    stubFetch(new Response("not json", { status: 200 }));

    const result = await convertImage(image(), SETTINGS);

    expect(result.ok).toBe(false);
  });

  it("says the server cannot be reached when fetch rejects", async () => {
    stubFetch(new TypeError("Failed to fetch"));

    const { message } = (await convertImage(image(), SETTINGS)) as { message: string };

    expect(message).toMatch(/cannot reach the server/i);
  });

  it("refuses a file one byte over the limit without any request", async () => {
    const fetchMock = stubFetch(json(200, PATTERN));

    const result = await convertImage(image(MAX_UPLOAD_BYTES + 1), SETTINGS);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result).toEqual({ ok: false, message: expect.stringContaining("20 MB") });
  });

  it("posts a file of exactly the limit", async () => {
    const fetchMock = stubFetch(json(200, PATTERN));

    await convertImage(image(MAX_UPLOAD_BYTES), SETTINGS);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("uses the API's limit of 20 * 1024 * 1024 bytes", () => {
    expect(MAX_UPLOAD_BYTES).toBe(20 * 1024 * 1024);
  });
});
