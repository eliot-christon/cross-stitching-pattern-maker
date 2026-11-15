import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  type RenderResult,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Limits } from "./api";
import type { Pattern } from "./pattern";
import { UploadForm } from "./UploadForm";

const PATTERN: Pattern = {
  width: 2,
  height: 1,
  fabric_count: 14,
  grid: [[0, 1]],
  key: [
    { code: "321", name: "Red", rgb: [199, 43, 59], stitches: 1, skeins: 1, symbol: "A", symbol_ink: "white" },
    { code: "310", name: "Black", rgb: [0, 0, 0], stitches: 1, skeins: 1, symbol: "B", symbol_ink: "white" },
  ],
  total_stitches: 2,
  finished_size: { width_in: 0.14, height_in: 0.07, width_cm: 0.36, height_cm: 0.18 },
  isolated_stitches: { before: 2, after: 0 },
  converted: null,
  ignored_replacements: [],
};

/** A second conversion, told apart from PATTERN on screen by its thread codes. */
const PATTERN_B: Pattern = {
  width: 3,
  height: 1,
  fabric_count: 14,
  grid: [[0, 0, 1]],
  key: [
    {
      code: "3865",
      name: "Winter White",
      rgb: [250, 246, 240],
      stitches: 2,
      skeins: 1,
      symbol: "A", symbol_ink: "black",
    },
    { code: "666", name: "Bright Red", rgb: [227, 29, 66], stitches: 1, skeins: 1, symbol: "B", symbol_ink: "white" },
  ],
  total_stitches: 3,
  finished_size: { width_in: 0.21, height_in: 0.07, width_cm: 0.54, height_cm: 0.18 },
  isolated_stitches: { before: 1, after: 0 },
  converted: null,
  ignored_replacements: [],
};

/** A thread only PATTERN's key holds, and one only PATTERN_B's holds. */
const A_CODE = "321";
const B_CODE = "666";

/** Limits unlike the API's real ones, so a number hard-coded in the page fails a test. */
const LIMITS: Limits = {
  max_upload_bytes: 1000,
  settings: {
    width: { min: 1, max: 500, step: 1, default: 100 },
    max_colours: { min: 1, max: 100, step: 1, default: 7 },
    merge_distance: { min: 0, max: 10, step: 0.5, default: 0 },
    min_stitches: { min: 0, max: 1000, step: 1, default: 0 },
    confetti_size: { min: 0, max: 10, step: 1, default: 0 },
    pages_across: { min: 1, max: 20, step: 1, default: 2 },
    pages_down: { min: 1, max: 20, step: 1, default: 2 },
    overlap: { min: 0, max: 5, step: 1, default: 2 },
  },
};

const WIDTH = "Width (stitches)";
const COLOURS = "Colours";
const MERGE = "Merge similar threads (colour distance)";
const MIN_STITCHES = "Minimum stitches per thread";
const CONFETTI = "Largest confetti cluster (stitches)";

/** The quiet delay after the last change before a conversion is sent. */
const QUIET_MS = 500;

/** What the status says while the preview is being updated. */
const BUSY = /converting|updating/i;

const NOT_AN_IMAGE = "the upload is not a decodable image";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** FastAPI's 422 body for one refused field. */
function refused(field: string, msg: string): Response {
  return json(422, { detail: [{ loc: ["body", field], msg, type: "value_error" }] });
}

type Handler = (init?: RequestInit) => Promise<Response>;

/**
 * fetch answering `/api/limits` with LIMITS, and the conversion and PDF URLs with their
 * handlers (a conversion of PATTERN by default).
 */
function stubApi(
  handlers: { patterns?: Handler; pdf?: Handler } = {},
): ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>> {
  const patterns = handlers.patterns ?? (() => Promise.resolve(json(200, PATTERN)));
  const pdf = handlers.pdf ?? (() => Promise.reject(new Error("no PDF expected")));
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === "/api/limits") {
      return Promise.resolve(json(200, LIMITS));
    }
    return url === "/api/patterns" ? patterns(init) : pdf(init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** The bodies posted to `url`, in order. */
function posted(fetchMock: ReturnType<typeof stubApi>, url: string): FormData[] {
  return fetchMock.mock.calls
    .filter(([calledUrl]) => calledUrl === url)
    .map(([, init]) => init?.body as FormData);
}

/** The value of `field` in each conversion posted, in order. */
function sent(fetchMock: ReturnType<typeof stubApi>, field: string): unknown[] {
  return posted(fetchMock, "/api/patterns").map((body) => body.get(field));
}

/** The name of the image in each conversion posted, in order. */
function sentImages(fetchMock: ReturnType<typeof stubApi>): string[] {
  return posted(fetchMock, "/api/patterns").map((body) => (body.get("image") as File).name);
}

/** Render the form and wait until the limits are in and it is shown. */
async function renderForm(): Promise<RenderResult> {
  const view = render(<UploadForm />);
  await screen.findByLabelText("Image");
  return view;
}

/**
 * Render the form with the real clock (the limits load through it), then take the clock
 * over: from here the test moves time itself. Only the timer functions are faked, so
 * promises, React's scheduling and the Response body readers run as usual.
 */
async function renderLive(): Promise<RenderResult> {
  const view = await renderForm();
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
  });
  return view;
}

/** Move the clock by `ms`, running the timers that fall due and what they cause. */
async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Let the requests already answered run to the end, without moving the clock. */
async function settle() {
  for (let round = 0; round < 3; round += 1) {
    await wait(0);
  }
}

/**
 * A conversion handler that answers only when the test says so: `answer(i, response)`
 * resolves the i-th conversion sent (from 0) and lets the page take it in.
 */
function controlled() {
  const pending: ((response: Response) => void)[] = [];
  const handler: Handler = () =>
    new Promise<Response>((resolve) => {
      pending.push(resolve);
    });
  async function answer(index: number, response: Response) {
    const resolve = pending[index];
    if (resolve === undefined) {
      throw new Error(`conversion ${String(index)} was never sent`);
    }
    await act(async () => {
      resolve(response);
    });
    await settle();
  }
  return { handler, answer };
}

function numberField(name: string): HTMLElement {
  return screen.getByRole("spinbutton", { name });
}

function slider(name: string): HTMLElement {
  return screen.getByRole("slider", { name });
}

function fabricCount(): HTMLElement {
  return screen.getByLabelText("Fabric count");
}

function imageInput(): HTMLElement {
  return screen.getByLabelText("Image");
}

function chooseFile(name = "photo.png", bytes = "png bytes"): File {
  const file = new File([bytes], name, { type: "image/png" });
  fireEvent.change(imageInput(), { target: { files: [file] } });
  return file;
}

function setValue(field: HTMLElement, value: string) {
  fireEvent.change(field, { target: { value } });
}

/** Whether the key on screen lists the thread `code`: which response the preview shows. */
function keyShows(code: string): boolean {
  return screen.queryByRole("cell", { name: code }) !== null;
}

function downloadButton(): HTMLElement {
  return screen.getByRole("button", { name: /pdf/i });
}

function convertButton(): HTMLElement | null {
  return screen.queryByRole("button", { name: /convert/i });
}

afterEach(() => {
  // Unmount under the clock the test used, so its pending timers go with the fake one.
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("UploadForm limits", () => {
  it("shows a status and no form while the limits load", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    render(<UploadForm />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading the settings/i);
    expect(convertButton()).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Image")).not.toBeInTheDocument();
  });

  it("says so, with no form, when the limits cannot be fetched", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    render(<UploadForm />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot reach the server/i);
    expect(screen.queryByLabelText("Image")).not.toBeInTheDocument();
  });

  it("asks for the limits once, at the limits URL", async () => {
    const fetchMock = stubApi();
    await renderForm();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/limits");
  });

  it("takes every slider's range, step and starting value from the limits", async () => {
    stubApi();
    await renderForm();

    const width = slider(WIDTH);
    expect(width).toHaveAttribute("min", "1");
    expect(width).toHaveAttribute("max", "500");
    expect(width).toHaveAttribute("step", "1");
    expect(width).toHaveValue("100");
    expect(numberField(WIDTH)).toHaveValue(100);
    expect(slider(COLOURS)).toHaveValue("7");
    expect(numberField(COLOURS)).toHaveValue(7);
    expect(slider(MERGE)).toHaveAttribute("step", "0.5");
    expect(slider(MERGE)).toHaveAttribute("max", "10");
    expect(slider(MIN_STITCHES)).toHaveAttribute("max", "1000");
    expect(slider(CONFETTI)).toHaveAttribute("max", "10");
    for (const name of [MERGE, MIN_STITCHES, CONFETTI]) {
      expect(numberField(name)).toHaveValue(0);
    }
  });

  it("keeps fabric count a number field at 14, with no slider", async () => {
    stubApi();
    await renderForm();

    expect(fabricCount()).toHaveValue(14);
    expect(screen.queryByRole("slider", { name: "Fabric count" })).not.toBeInTheDocument();
  });

  it("moves the number field with the slider and posts the slider's value", async () => {
    const fetchMock = stubApi();
    await renderLive();

    chooseFile();
    setValue(slider(CONFETTI), "3");
    expect(numberField(CONFETTI)).toHaveValue(3);
    await wait(QUIET_MS);
    await settle();

    expect(screen.getByRole("table", { name: "Thread key" })).toBeInTheDocument();
    expect(sent(fetchMock, "confetti_size")).toEqual(["3"]);
  });

  it("moves the slider with the number field", async () => {
    stubApi();
    await renderForm();

    setValue(numberField(WIDTH), "250");

    expect(slider(WIDTH)).toHaveValue("250");
  });

  it("refuses an image over the reported upload limit without converting", async () => {
    const fetchMock = stubApi();
    await renderLive();

    chooseFile("big.png", "x".repeat(1001));
    await wait(QUIET_MS);
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent("larger than 1000 bytes");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await wait(5000);
    expect(posted(fetchMock, "/api/patterns")).toHaveLength(0);
  });
});

describe("UploadForm live conversion", () => {
  it("starts with the reported settings and sends nothing before an image is chosen", async () => {
    const fetchMock = stubApi();
    await renderLive();

    expect(numberField(WIDTH)).toHaveValue(100);
    expect(numberField(COLOURS)).toHaveValue(7);
    expect(fabricCount()).toHaveValue(14);
    expect(numberField(MERGE)).toHaveValue(0);
    expect(numberField(MIN_STITCHES)).toHaveValue(0);
    expect(numberField(CONFETTI)).toHaveValue(0);
    expect(convertButton()).not.toBeInTheDocument();

    setValue(numberField(WIDTH), "50");
    await wait(2 * QUIET_MS);

    expect(posted(fetchMock, "/api/patterns")).toHaveLength(0);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Thread key" })).not.toBeInTheDocument();
  });

  it("converts a chosen image once nothing has changed for 500 ms, with no Convert button", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();

    const file = chooseFile();
    expect(screen.getByRole("status")).toHaveTextContent(BUSY);
    await wait(QUIET_MS - 1);
    expect(posted(fetchMock, "/api/patterns")).toHaveLength(0);

    await wait(1);
    expect(sentImages(fetchMock)).toEqual([file.name]);
    expect(screen.getByRole("status")).toHaveTextContent(BUSY);

    await calls.answer(0, json(200, PATTERN));

    expect(keyShows(A_CODE)).toBe(true);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(convertButton()).not.toBeInTheDocument();
    await wait(10 * QUIET_MS);
    expect(posted(fetchMock, "/api/patterns")).toHaveLength(1);
  });

  it("posts the chosen file with the values entered, as one request", async () => {
    const fetchMock = stubApi();
    await renderLive();

    const file = chooseFile();
    setValue(numberField(WIDTH), "40");
    setValue(numberField(COLOURS), "4");
    setValue(fabricCount(), "16");
    setValue(numberField(MERGE), "2.5");
    setValue(numberField(MIN_STITCHES), "10");
    setValue(numberField(CONFETTI), "3");
    await wait(QUIET_MS);
    await settle();

    expect(screen.getByRole("table", { name: "Thread key" })).toBeInTheDocument();
    const bodies = posted(fetchMock, "/api/patterns");
    expect(bodies).toHaveLength(1);
    const body = bodies[0] as FormData;
    expect((body.get("image") as File).name).toBe(file.name);
    expect(body.get("width")).toBe("40");
    expect(body.get("max_colours")).toBe("4");
    expect(body.get("fabric_count")).toBe("16");
    expect(body.get("merge_distance")).toBe("2.5");
    expect(body.get("min_stitches")).toBe("10");
    expect(body.get("confetti_size")).toBe("3");
  });

  it("posts the reported defaults when the settings are left alone", async () => {
    const fetchMock = stubApi();
    await renderLive();

    chooseFile();
    await wait(QUIET_MS);
    await settle();

    const body = posted(fetchMock, "/api/patterns")[0] as FormData;
    expect(body.get("width")).toBe("100");
    expect(body.get("max_colours")).toBe("7");
    expect(body.get("fabric_count")).toBe("14");
    expect(body.get("merge_distance")).toBe("0");
    expect(body.get("min_stitches")).toBe("0");
    expect(body.get("confetti_size")).toBe("0");
  });

  it("sends one conversion 500 ms after the last of three slider changes, with the third value", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);
    await calls.answer(0, json(200, PATTERN));

    setValue(slider(WIDTH), "50");
    await wait(100);
    setValue(slider(WIDTH), "60");
    await wait(100);
    setValue(slider(WIDTH), "70");
    await wait(QUIET_MS - 1);
    expect(sent(fetchMock, "width")).toEqual(["100"]);

    await wait(1);
    expect(sent(fetchMock, "width")).toEqual(["100", "70"]);
  });

  it.each([
    { control: "width slider", field: () => slider(WIDTH), name: "width", value: "60" },
    {
      control: "max colours number field",
      field: () => numberField(COLOURS),
      name: "max_colours",
      value: "5",
    },
    { control: "fabric count field", field: fabricCount, name: "fabric_count", value: "18" },
    { control: "merge slider", field: () => slider(MERGE), name: "merge_distance", value: "1.5" },
    {
      control: "minimum stitches number field",
      field: () => numberField(MIN_STITCHES),
      name: "min_stitches",
      value: "4",
    },
    {
      control: "confetti slider",
      field: () => slider(CONFETTI),
      name: "confetti_size",
      value: "2",
    },
  ])(
    "re-converts 500 ms after a change of the $control",
    async ({ field, name, value }) => {
      const calls = controlled();
      const fetchMock = stubApi({ patterns: calls.handler });
      await renderLive();
      chooseFile();
      await wait(QUIET_MS);
      await calls.answer(0, json(200, PATTERN));

      setValue(field(), value);
      await wait(QUIET_MS - 1);
      expect(posted(fetchMock, "/api/patterns")).toHaveLength(1);

      await wait(1);
      expect(sent(fetchMock, name)).toHaveLength(2);
      expect(sent(fetchMock, name)[1]).toBe(value);
    },
  );

  it("never converts on a change of the chart choices", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);
    await calls.answer(0, json(200, PATTERN));

    setValue(screen.getByLabelText("Chart"), "bw");
    setValue(screen.getByLabelText("Paper"), "A3");
    setValue(screen.getByLabelText("Orientation"), "landscape");

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await wait(10 * QUIET_MS);
    expect(posted(fetchMock, "/api/patterns")).toHaveLength(1);
    expect(downloadButton()).toBeEnabled();
  });

  it("sends nothing when confetti goes to 3 and back to the preview's 0 within 500 ms", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);
    await calls.answer(0, json(200, PATTERN));

    setValue(slider(CONFETTI), "3");
    await wait(200);
    setValue(numberField(CONFETTI), "0");
    await wait(2 * QUIET_MS);

    expect(posted(fetchMock, "/api/patterns")).toHaveLength(1);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(keyShows(A_CODE)).toBe(true);
    expect(downloadButton()).toBeEnabled();
  });

  it("shows a status while an update is pending or running, with the previous preview kept", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);
    await calls.answer(0, json(200, PATTERN));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    setValue(numberField(MIN_STITCHES), "4");

    expect(screen.getByRole("status")).toHaveTextContent(BUSY);
    expect(keyShows(A_CODE)).toBe(true);

    await wait(QUIET_MS);
    expect(posted(fetchMock, "/api/patterns")).toHaveLength(2);
    expect(screen.getByRole("status")).toHaveTextContent(BUSY);
    expect(keyShows(A_CODE)).toBe(true);

    await calls.answer(1, json(200, PATTERN_B));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(keyShows(B_CODE)).toBe(true);
    expect(keyShows(A_CODE)).toBe(false);
  });

  it("clears the preview and sends nothing when the image is cleared", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);
    await calls.answer(0, json(200, PATTERN));

    setValue(slider(WIDTH), "60");
    fireEvent.change(imageInput(), { target: { files: [] } });

    expect(keyShows(A_CODE)).toBe(false);
    expect(screen.queryByRole("button", { name: /pdf/i })).not.toBeInTheDocument();
    await wait(10 * QUIET_MS);
    expect(posted(fetchMock, "/api/patterns")).toHaveLength(1);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("sends nothing after unmounting with a change pending", async () => {
    const fetchMock = stubApi();
    const { unmount } = await renderLive();

    chooseFile();
    await wait(200);
    unmount();
    await wait(10 * QUIET_MS);

    expect(posted(fetchMock, "/api/patterns")).toHaveLength(0);
  });

  it("sends no follow-up and logs no error after unmounting while a conversion runs", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    const { unmount } = await renderLive();
    const errors = vi.spyOn(console, "error");
    chooseFile();
    await wait(QUIET_MS);
    setValue(slider(WIDTH), "60");
    await wait(2 * QUIET_MS);

    unmount();
    await calls.answer(0, json(200, PATTERN));
    await wait(10 * QUIET_MS);

    expect(posted(fetchMock, "/api/patterns")).toHaveLength(1);
    expect(errors).not.toHaveBeenCalled();
  });
});

describe("UploadForm one conversion at a time", () => {
  it("holds a change made while A runs until A ends, shows A, then sends one B", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);

    setValue(slider(WIDTH), "60");
    await wait(2 * QUIET_MS);
    expect(sent(fetchMock, "width")).toEqual(["100"]);
    expect(screen.getByRole("status")).toHaveTextContent(BUSY);

    await calls.answer(0, json(200, PATTERN));

    expect(keyShows(A_CODE)).toBe(true);
    expect(sent(fetchMock, "width")).toEqual(["100", "60"]);
    expect(screen.getByRole("status")).toHaveTextContent(BUSY);
  });

  it("coalesces three changes made while A runs into one follow-up with the last value", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);

    setValue(slider(WIDTH), "50");
    await wait(100);
    setValue(slider(WIDTH), "60");
    await wait(100);
    setValue(numberField(WIDTH), "70");
    await wait(2 * QUIET_MS);
    expect(sent(fetchMock, "width")).toEqual(["100"]);

    await calls.answer(0, json(200, PATTERN));
    expect(sent(fetchMock, "width")).toEqual(["100", "70"]);

    await calls.answer(1, json(200, PATTERN_B));
    await wait(10 * QUIET_MS);
    expect(sent(fetchMock, "width")).toEqual(["100", "70"]);
  });

  it("lets the follow-up wait out the quiet delay when A ends before it expires", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);
    await wait(300);

    setValue(slider(WIDTH), "60");
    await wait(100);
    await calls.answer(0, json(200, PATTERN));
    expect(sent(fetchMock, "width")).toEqual(["100"]);

    await wait(QUIET_MS - 100 - 1);
    expect(sent(fetchMock, "width")).toEqual(["100"]);

    await wait(1);
    expect(sent(fetchMock, "width")).toEqual(["100", "60"]);
  });

  it("restarts the quiet delay for a change made after a follow-up fell due", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);

    setValue(slider(WIDTH), "60");
    await wait(QUIET_MS);
    setValue(slider(WIDTH), "70");
    await wait(100);
    await calls.answer(0, json(200, PATTERN));
    expect(sent(fetchMock, "width")).toEqual(["100"]);

    await wait(QUIET_MS - 100 - 1);
    expect(sent(fetchMock, "width")).toEqual(["100"]);

    await wait(1);
    expect(sent(fetchMock, "width")).toEqual(["100", "70"]);
  });

  it("sends no follow-up when a change made while A runs is undone before A ends", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);

    setValue(slider(WIDTH), "60");
    await wait(100);
    setValue(numberField(WIDTH), "100");
    await wait(2 * QUIET_MS);
    await calls.answer(0, json(200, PATTERN));
    await wait(10 * QUIET_MS);

    expect(sent(fetchMock, "width")).toEqual(["100"]);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(keyShows(A_CODE)).toBe(true);
  });

  it("replaces A's preview with B's, which stays, with nothing sent after it", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);
    setValue(slider(WIDTH), "60");
    await wait(QUIET_MS);
    await calls.answer(0, json(200, PATTERN));
    expect(keyShows(A_CODE)).toBe(true);

    await calls.answer(1, json(200, PATTERN_B));

    expect(keyShows(B_CODE)).toBe(true);
    expect(keyShows(A_CODE)).toBe(false);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await wait(20 * QUIET_MS);
    expect(keyShows(B_CODE)).toBe(true);
    expect(keyShows(A_CODE)).toBe(false);
    expect(posted(fetchMock, "/api/patterns")).toHaveLength(2);
  });
});

describe("UploadForm errors and image changes", () => {
  it("keeps the preview and its download on a 422 naming width, until a success clears the alert", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);
    await calls.answer(0, json(200, PATTERN));

    setValue(numberField(WIDTH), "900");
    await wait(QUIET_MS);
    await calls.answer(1, refused("width", "Input should be less than or equal to 500"));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "width: Input should be less than or equal to 500",
    );
    expect(keyShows(A_CODE)).toBe(true);
    expect(downloadButton()).toBeEnabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    setValue(numberField(WIDTH), "50");
    await wait(QUIET_MS);
    await calls.answer(2, json(200, PATTERN_B));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(keyShows(B_CODE)).toBe(true);
    expect(sent(fetchMock, "width")).toEqual(["100", "900", "50"]);
  });

  it("shows the field of a refused cleanup setting from the API's 422", async () => {
    stubApi({
      patterns: () =>
        Promise.resolve(refused("confetti_size", "Input should be less than or equal to 10")),
    });
    await renderLive();

    chooseFile();
    setValue(numberField(CONFETTI), "11");
    await wait(QUIET_MS);
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent(
      "confetti_size: Input should be less than or equal to 10",
    );
  });

  it("posts a width of 0 as typed: the form does no range check", async () => {
    const fetchMock = stubApi({
      patterns: () =>
        Promise.resolve(refused("width", "Input should be greater than or equal to 1")),
    });
    await renderLive();

    chooseFile();
    setValue(numberField(WIDTH), "0");
    await wait(QUIET_MS);
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent(
      "width: Input should be greater than or equal to 1",
    );
    expect(sent(fetchMock, "width")).toEqual(["0"]);
  });

  it("shows the API's message on an error", async () => {
    stubApi({ patterns: () => Promise.resolve(json(400, { detail: NOT_AN_IMAGE })) });
    await renderLive();

    chooseFile();
    await wait(QUIET_MS);
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent(NOT_AN_IMAGE);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not send a failed conversion again while its settings stand", async () => {
    const fetchMock = stubApi({
      patterns: () => Promise.resolve(json(400, { detail: NOT_AN_IMAGE })),
    });
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent(NOT_AN_IMAGE);

    await wait(20 * QUIET_MS);
    expect(posted(fetchMock, "/api/patterns")).toHaveLength(1);

    setValue(slider(WIDTH), "50");
    await wait(200);
    setValue(numberField(WIDTH), "100");
    await wait(2 * QUIET_MS);

    expect(posted(fetchMock, "/api/patterns")).toHaveLength(1);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows a message, not a crash, when the server cannot be reached", async () => {
    stubApi({ patterns: () => Promise.reject(new TypeError("Failed to fetch")) });
    await renderLive();

    chooseFile();
    await wait(QUIET_MS);
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent(/cannot reach the server/i);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("clears the preview at once when another image is chosen, then converts that image", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile("photo.png");
    await wait(QUIET_MS);
    await calls.answer(0, json(200, PATTERN));

    chooseFile("other.png");

    expect(keyShows(A_CODE)).toBe(false);
    expect(screen.queryByRole("button", { name: /pdf/i })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(BUSY);

    await wait(QUIET_MS);
    expect(sentImages(fetchMock)).toEqual(["photo.png", "other.png"]);
    await calls.answer(1, json(200, PATTERN_B));
    expect(keyShows(B_CODE)).toBe(true);
  });

  it("clears the error at once when another image is chosen", async () => {
    const calls = controlled();
    stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile("photo.png");
    await wait(QUIET_MS);
    await calls.answer(0, json(400, { detail: NOT_AN_IMAGE }));
    expect(screen.getByRole("alert")).toHaveTextContent(NOT_AN_IMAGE);

    chooseFile("other.png");

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the alert and no preview when a new image's conversion fails", async () => {
    const calls = controlled();
    stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile("photo.png");
    await wait(QUIET_MS);
    await calls.answer(0, json(200, PATTERN));

    chooseFile("other.png");
    await wait(QUIET_MS);
    await calls.answer(1, json(400, { detail: NOT_AN_IMAGE }));

    expect(screen.getByRole("alert")).toHaveTextContent(NOT_AN_IMAGE);
    expect(keyShows(A_CODE)).toBe(false);
    expect(screen.queryByRole("table", { name: "Thread key" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /pdf/i })).not.toBeInTheDocument();
  });

  it("discards a preview of the image no longer chosen, then sends the new image's request", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile("photo.png");
    await wait(QUIET_MS);

    chooseFile("other.png");
    await wait(2 * QUIET_MS);
    expect(sentImages(fetchMock)).toEqual(["photo.png"]);

    await calls.answer(0, json(200, PATTERN));

    expect(keyShows(A_CODE)).toBe(false);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(sentImages(fetchMock)).toEqual(["photo.png", "other.png"]);
    expect(screen.getByRole("status")).toHaveTextContent(BUSY);

    await calls.answer(1, json(200, PATTERN_B));
    expect(keyShows(B_CODE)).toBe(true);
  });

  it("discards a failure for the image no longer chosen, with no alert", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ patterns: calls.handler });
    await renderLive();
    chooseFile("photo.png");
    await wait(QUIET_MS);

    chooseFile("other.png");
    await wait(2 * QUIET_MS);
    await calls.answer(0, json(400, { detail: NOT_AN_IMAGE }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(sentImages(fetchMock)).toEqual(["photo.png", "other.png"]);
  });
});

describe("UploadForm PDF download", () => {
  function pdfResponse(): Response {
    return new Response("%PDF-1.4 chart", {
      status: 200,
      headers: { "Content-Type": "application/pdf" },
    });
  }

  function stubSave() {
    // jsdom has no object URLs: a subclass stands in, leaving the real URL untouched.
    const createObjectURL = vi.fn(() => "blob:chart");
    vi.stubGlobal(
      "URL",
      class extends URL {
        static override createObjectURL = createObjectURL;
        static override revokeObjectURL = vi.fn();
      },
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    return { createObjectURL, click };
  }

  /** Choose an image at `width` and let its conversion (answered at once) show. */
  async function convert(width = "40") {
    chooseFile();
    setValue(numberField(WIDTH), width);
    await wait(QUIET_MS);
    await settle();
    expect(screen.getByRole("table", { name: "Thread key" })).toBeInTheDocument();
  }

  it("offers no download before a conversion", async () => {
    stubApi();
    await renderForm();

    expect(screen.queryByRole("button", { name: /pdf/i })).not.toBeInTheDocument();
  });

  it("offers the download with colour, A4 and portrait chosen after a conversion", async () => {
    stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    await renderLive();

    await convert();

    expect(downloadButton()).toHaveTextContent("Download PDF");
    expect(downloadButton()).toBeEnabled();
    expect(screen.getByLabelText("Chart")).toHaveValue("colour");
    expect(screen.getByLabelText("Paper")).toHaveValue("A4");
    expect(screen.getByLabelText("Orientation")).toHaveValue("portrait");
    const papers = Array.from(
      (screen.getByLabelText("Paper") as HTMLSelectElement).options,
      (option) => option.value,
    );
    expect(papers).toEqual(["A2", "A3", "A4", "A5"]);
  });

  it("asks for the PDF of the preview shown, with the choices made, and saves it", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    const { createObjectURL, click } = stubSave();
    await renderLive();

    setValue(numberField(CONFETTI), "3");
    await convert("40");
    setValue(screen.getByLabelText("Chart"), "bw");
    setValue(screen.getByLabelText("Paper"), "A3");
    setValue(screen.getByLabelText("Orientation"), "landscape");
    fireEvent.click(downloadButton());
    await settle();

    expect(click).toHaveBeenCalledTimes(1);
    const pdfs = posted(fetchMock, "/api/patterns/pdf");
    expect(pdfs).toHaveLength(1);
    const body = pdfs[0] as FormData;
    expect((body.get("image") as File).name).toBe("photo.png");
    expect(body.get("width")).toBe("40");
    expect(body.get("max_colours")).toBe("7");
    expect(body.get("fabric_count")).toBe("14");
    expect(body.get("confetti_size")).toBe("3");
    expect(body.get("merge_distance")).toBe("0");
    expect(body.get("variant")).toBe("bw");
    expect(body.get("paper")).toBe("A3");
    expect(body.get("orientation")).toBe("landscape");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const link = click.mock.contexts[0] as HTMLAnchorElement;
    expect(link.download).toBe("pattern.pdf");
    expect(link.href).toBe("blob:chart");
  });

  it("disables the download while an update is pending or running, then asks for B's settings", async () => {
    const calls = controlled();
    const fetchMock = stubApi({
      patterns: calls.handler,
      pdf: () => Promise.resolve(pdfResponse()),
    });
    const { click } = stubSave();
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);
    await calls.answer(0, json(200, PATTERN));
    expect(downloadButton()).toBeEnabled();

    setValue(slider(WIDTH), "80");
    setValue(numberField(CONFETTI), "5");
    expect(downloadButton()).toBeDisabled();
    fireEvent.click(downloadButton());
    await wait(QUIET_MS);
    expect(posted(fetchMock, "/api/patterns")).toHaveLength(2);
    expect(downloadButton()).toBeDisabled();

    await calls.answer(1, json(200, PATTERN_B));

    expect(keyShows(B_CODE)).toBe(true);
    expect(downloadButton()).toBeEnabled();
    expect(posted(fetchMock, "/api/patterns/pdf")).toHaveLength(0);
    fireEvent.click(downloadButton());
    await settle();

    expect(click).toHaveBeenCalledTimes(1);
    const pdfs = posted(fetchMock, "/api/patterns/pdf");
    expect(pdfs).toHaveLength(1);
    const body = pdfs[0] as FormData;
    expect(body.get("width")).toBe("80");
    expect(body.get("confetti_size")).toBe("5");
    expect(body.get("max_colours")).toBe("7");
  });

  it("asks for the PDF of the preview kept after a failed update", async () => {
    const calls = controlled();
    const fetchMock = stubApi({
      patterns: calls.handler,
      pdf: () => Promise.resolve(pdfResponse()),
    });
    const { click } = stubSave();
    await renderLive();
    chooseFile();
    await wait(QUIET_MS);
    await calls.answer(0, json(200, PATTERN));
    setValue(numberField(WIDTH), "900");
    await wait(QUIET_MS);
    await calls.answer(1, refused("width", "Input should be less than or equal to 500"));

    fireEvent.click(downloadButton());
    await settle();

    expect(click).toHaveBeenCalledTimes(1);
    const body = posted(fetchMock, "/api/patterns/pdf")[0] as FormData;
    expect(body.get("width")).toBe("100");
  });

  it("disables the button and says so while the PDF is being made", async () => {
    let resolve: (response: Response) => void = () => undefined;
    stubApi({ pdf: () => new Promise<Response>((done) => (resolve = done)) });
    stubSave();
    await renderLive();
    await convert();

    fireEvent.click(downloadButton());
    await settle();

    expect(screen.getByRole("button", { name: "Preparing PDF..." })).toBeDisabled();

    await act(async () => resolve(pdfResponse()));
    await settle();

    expect(downloadButton()).toHaveTextContent("Download PDF");
    expect(downloadButton()).toBeEnabled();
  });

  it("clears a failed download's message once the next preview shows", async () => {
    stubApi({ pdf: () => Promise.resolve(refused("paper", "bad paper")) });
    await renderLive();
    await convert();
    fireEvent.click(downloadButton());
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent("paper: bad paper");

    setValue(numberField(WIDTH), "60");
    await wait(QUIET_MS);
    await settle();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(downloadButton()).toHaveTextContent("Download PDF");
  });

  it("drops the PDF of an image no longer chosen and offers the new one's", async () => {
    let resolve: (response: Response) => void = () => undefined;
    const fetchMock = stubApi({ pdf: () => new Promise<Response>((done) => (resolve = done)) });
    const { click } = stubSave();
    await renderLive();
    await convert();
    fireEvent.click(downloadButton());
    await settle();

    chooseFile("other.png");
    await wait(QUIET_MS);
    await settle();
    expect(downloadButton()).toHaveTextContent("Download PDF");
    expect(downloadButton()).toBeEnabled();

    await act(async () => resolve(pdfResponse()));
    await settle();

    expect(click).not.toHaveBeenCalled();
    expect(downloadButton()).toBeEnabled();
    expect(sentImages(fetchMock)).toEqual(["photo.png", "other.png"]);
  });

  it("shows the API's message on a failed download and keeps the preview", async () => {
    stubApi({
      pdf: () => Promise.resolve(refused("paper", "bad paper")),
    });
    await renderLive();
    await convert();

    fireEvent.click(downloadButton());
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent("paper: bad paper");
    expect(screen.getByRole("table", { name: "Thread key" })).toBeInTheDocument();
  });
});

describe("thread replacements", () => {
  const TABLE = [
    { code: "310", name: "Black", rgb: [0, 0, 0] },
    { code: "321", name: "Red", rgb: [199, 43, 59] },
    { code: "3865", name: "Winter White", rgb: [249, 247, 241] },
    { code: "3371", name: "Black Brown", rgb: [30, 17, 8] },
  ];
  const NEAREST = [
    { code: "3371", name: "Black Brown", rgb: [30, 17, 8], distance: 4.2 },
    { code: "3865", name: "Winter White", rgb: [249, 247, 241], distance: 90 },
  ];

  /** stubApi, plus the thread table and nearest threads the picker asks for. */
  function stubWithThreads(handlers: { patterns?: Handler; pdf?: Handler } = {}) {
    const inner = stubApi(handlers);
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/threads") {
        return Promise.resolve(json(200, TABLE));
      }
      if (url.startsWith("/api/threads/")) {
        return Promise.resolve(json(200, NEAREST));
      }
      return inner(url, init);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  /** The `replace` fields of each conversion posted, in order. */
  function sentReplacements(fetchMock: ReturnType<typeof stubApi>): string[][] {
    return posted(fetchMock, "/api/patterns").map((body) => body.getAll("replace") as string[]);
  }

  /** Open the picker on the key entry `code` and choose the thread named `name`. */
  async function replace(code: string, name: string) {
    fireEvent.click(screen.getByRole("cell", { name: code }));
    await settle();
    const picker = screen.getByRole("dialog");
    fireEvent.click(within(picker).getAllByText(name)[0] as HTMLElement);
    await settle();
  }

  async function preview() {
    chooseFile();
    await wait(QUIET_MS);
    await settle();
    expect(keyShows(A_CODE)).toBe(true);
  }

  function replacementItems(): HTMLElement[] {
    const section = screen.queryByRole("region", { name: "Replacements" });
    return section === null ? [] : within(section).getAllByRole("listitem");
  }

  it("sends a picked replacement after the quiet delay and lists it", async () => {
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();

    await replace("310", "Winter White");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await wait(QUIET_MS - 1);
    expect(sentReplacements(fetchMock)).toEqual([[]]);
    await wait(1);
    await settle();

    expect(sentReplacements(fetchMock)).toEqual([[], ["310:3865"]]);
    expect(replacementItems()).toHaveLength(1);
    expect(replacementItems()[0]).toHaveTextContent(/310.*Black.*3865.*Winter White/);
  });

  it("sends nothing when a pair is undone and picked again within the quiet delay", async () => {
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    await wait(QUIET_MS);
    await settle();

    fireEvent.click(screen.getByRole("button", { name: "Undo 310 to 3865" }));
    await replace("310", "Winter White");
    await wait(10 * QUIET_MS);

    expect(sentReplacements(fetchMock)).toEqual([[], ["310:3865"]]);
  });

  it("sends no replace field once the only pair is undone, and hides the list", async () => {
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    await wait(QUIET_MS);
    await settle();

    fireEvent.click(screen.getByRole("button", { name: "Undo 310 to 3865" }));
    await wait(QUIET_MS);
    await settle();

    expect(sentReplacements(fetchMock)).toEqual([[], ["310:3865"], []]);
    expect(screen.queryByRole("region", { name: "Replacements" })).not.toBeInTheDocument();
  });

  it("sends one request with no replace field after a reset of two pairs", async () => {
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    await replace("321", "Black Brown");
    await wait(QUIET_MS);
    await settle();
    expect(sentReplacements(fetchMock).at(-1)).toEqual(["310:3865", "321:3371"]);

    fireEvent.click(screen.getByRole("button", { name: "Reset replacements" }));
    await wait(QUIET_MS);
    await settle();

    expect(sentReplacements(fetchMock)).toEqual([[], ["310:3865", "321:3371"], []]);
  });

  it("marks the pair the response ignored, and keeps the mark on it after an undo", async () => {
    stubWithThreads({
      patterns: () => Promise.resolve(json(200, { ...PATTERN, ignored_replacements: [1] })),
    });
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    await replace("321", "Black Brown");
    await wait(QUIET_MS);
    await settle();

    const [first, second] = replacementItems();
    expect(first).not.toHaveTextContent(/not in the pattern/);
    expect(second).toHaveTextContent(/321.*not in the pattern/);

    fireEvent.click(screen.getByRole("button", { name: "Undo 310 to 3865" }));

    expect(replacementItems()).toHaveLength(1);
    expect(replacementItems()[0]).toHaveTextContent(/321.*not in the pattern/);
  });

  it("sends the pairs with a width change", async () => {
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    await wait(QUIET_MS);
    await settle();

    setValue(numberField(WIDTH), "55");
    await wait(QUIET_MS);
    await settle();

    const last = posted(fetchMock, "/api/patterns").at(-1);
    expect(last?.get("width")).toBe("55");
    expect(last?.getAll("replace")).toEqual(["310:3865"]);
  });

  it("asks for the PDF with the pairs that produced the preview", async () => {
    const fetchMock = stubWithThreads({
      pdf: () =>
        Promise.resolve(
          new Response("%PDF-1.4 chart", {
            status: 200,
            headers: { "Content-Type": "application/pdf" },
          }),
        ),
    });
    vi.stubGlobal(
      "URL",
      class extends URL {
        static override createObjectURL = vi.fn(() => "blob:chart");
        static override revokeObjectURL = vi.fn();
      },
    );
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    await wait(QUIET_MS);
    await settle();

    fireEvent.click(downloadButton());
    await settle();

    const pdfs = posted(fetchMock, "/api/patterns/pdf");
    expect(pdfs).toHaveLength(1);
    expect(pdfs[0]?.getAll("replace")).toEqual(["310:3865"]);
  });

  it("keeps the pairs when another image is chosen and sends them with it", async () => {
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    await wait(QUIET_MS);
    await settle();

    const other = chooseFile("other.png");
    await wait(QUIET_MS);
    await settle();

    const last = posted(fetchMock, "/api/patterns").at(-1);
    const image = last?.get("image");
    expect(image instanceof File ? image.name : null).toBe(other.name);
    expect(last?.getAll("replace")).toEqual(["310:3865"]);
    expect(replacementItems()).toHaveLength(1);
  });
});

describe("PDF chart layout", () => {
  function pdfResponse(): Response {
    return new Response("%PDF-1.4 chart", {
      status: 200,
      headers: { "Content-Type": "application/pdf" },
    });
  }

  function stubSave() {
    vi.stubGlobal(
      "URL",
      class extends URL {
        static override createObjectURL = vi.fn(() => "blob:chart");
        static override revokeObjectURL = vi.fn();
      },
    );
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  }

  async function preview() {
    chooseFile();
    await wait(QUIET_MS);
    await settle();
    expect(keyShows(A_CODE)).toBe(true);
  }

  function lastPdf(fetchMock: ReturnType<typeof stubApi>): FormData | undefined {
    return posted(fetchMock, "/api/patterns/pdf").at(-1);
  }

  it("starts at the reported overlap, centre lines off, and no pages fields", async () => {
    stubApi();
    await renderLive();
    await preview();

    expect(numberField("Repeated rows and columns")).toHaveValue(2);
    expect(screen.getByRole("checkbox", { name: "Centre lines in the PDF" })).not.toBeChecked();
    expect(screen.queryByRole("spinbutton", { name: "Pages across" })).not.toBeInTheDocument();
  });

  it("shows the pages fields only for a split by pages", async () => {
    stubApi();
    await renderLive();
    await preview();

    setValue(screen.getByLabelText("Split"), "pages");
    expect(numberField("Pages across")).toHaveValue(2);
    expect(numberField("Pages down")).toHaveValue(2);

    setValue(screen.getByLabelText("Split"), "cells");
    expect(screen.queryByRole("spinbutton", { name: "Pages across" })).not.toBeInTheDocument();
  });

  it("asks for the default layout by default", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubSave();
    await renderLive();
    await preview();

    fireEvent.click(downloadButton());
    await settle();

    const body = lastPdf(fetchMock);
    expect(body?.get("split")).toBe("cells");
    expect(body?.get("overlap")).toBe("2");
    expect(body?.get("centre_lines")).toBe("false");
  });

  it("asks for the layout chosen", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubSave();
    await renderLive();
    await preview();

    setValue(screen.getByLabelText("Split"), "pages");
    setValue(numberField("Pages across"), "3");
    setValue(numberField("Repeated rows and columns"), "0");
    fireEvent.click(screen.getByRole("checkbox", { name: "Centre lines in the PDF" }));
    fireEvent.click(downloadButton());
    await settle();

    const body = lastPdf(fetchMock);
    expect(
      ["split", "pages_across", "pages_down", "overlap", "centre_lines"].map((n) => body?.get(n)),
    ).toEqual(["pages", "3", "2", "0", "true"]);
  });

  it("shows a refused layout field from the API and keeps the preview", async () => {
    stubApi({ pdf: () => Promise.resolve(refused("pages_across", "must be at most 20")) });
    await renderLive();
    await preview();

    fireEvent.click(downloadButton());
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent("pages_across: must be at most 20");
    expect(keyShows(A_CODE)).toBe(true);
  });
});

describe("PDF view", () => {
  let made = 0;
  let revoked: string[] = [];

  function pdfResponse(): Response {
    return new Response("%PDF-1.4 chart", {
      status: 200,
      headers: { "Content-Type": "application/pdf" },
    });
  }

  /** Object URLs counted (blob:pdf-1, blob:pdf-2, ...) and their revocations recorded. */
  function stubUrls() {
    made = 0;
    revoked = [];
    vi.stubGlobal(
      "URL",
      class extends URL {
        static override createObjectURL = vi.fn(() => {
          made += 1;
          return `blob:pdf-${String(made)}`;
        });
        static override revokeObjectURL = vi.fn((url: string) => {
          revoked.push(url);
        });
      },
    );
    return vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  }

  async function preview() {
    chooseFile();
    await wait(QUIET_MS);
    await settle();
    expect(keyShows(A_CODE)).toBe(true);
  }

  function pdfRequests(fetchMock: ReturnType<typeof stubApi>): FormData[] {
    return posted(fetchMock, "/api/patterns/pdf");
  }

  function frameUrl(): string | null {
    return screen.queryByTitle("PDF chart preview")?.getAttribute("src") ?? null;
  }

  function showPdf() {
    fireEvent.click(screen.getByRole("radio", { name: "PDF" }));
  }

  it("asks for nothing while the pattern is shown", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubUrls();
    await renderLive();
    await preview();

    await wait(2000);

    expect(pdfRequests(fetchMock)).toHaveLength(0);
  });

  it("asks at once when shown, then shows the PDF with a link to it", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubUrls();
    await renderLive();
    await preview();

    showPdf();
    await settle();

    const requests = pdfRequests(fetchMock);
    expect(requests).toHaveLength(1);
    expect(requests[0]?.get("width")).toBe("100");
    expect(requests[0]?.get("paper")).toBe("A4");
    expect(frameUrl()).toBe("blob:pdf-1");
    expect(screen.getByRole("link", { name: "Open in a new tab" })).toHaveAttribute(
      "href",
      "blob:pdf-1",
    );
  });

  it("follows a chart change after the quiet delay and revokes the old PDF", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubUrls();
    await renderLive();
    await preview();
    showPdf();
    await settle();

    setValue(screen.getByLabelText("Paper"), "A3");
    await wait(QUIET_MS - 1);
    expect(pdfRequests(fetchMock)).toHaveLength(1);
    expect(frameUrl()).toBe("blob:pdf-1");
    expect(screen.getByText("Making the PDF...")).toBeInTheDocument();

    await wait(1);
    await settle();

    expect(pdfRequests(fetchMock).at(-1)?.get("paper")).toBe("A3");
    expect(frameUrl()).toBe("blob:pdf-2");
    expect(revoked).toContain("blob:pdf-1");
  });

  it("waits for a conversion, then asks once with the new settings", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubUrls();
    await renderLive();
    await preview();
    showPdf();
    await settle();

    setValue(numberField(WIDTH), "55");
    await wait(QUIET_MS - 1);
    expect(pdfRequests(fetchMock)).toHaveLength(1);
    await wait(1);
    await settle();

    expect(pdfRequests(fetchMock)).toHaveLength(2);
    expect(pdfRequests(fetchMock).at(-1)?.get("width")).toBe("55");
  });

  it("sends one follow-up for changes made while a PDF is being made", async () => {
    const calls = controlled();
    const fetchMock = stubApi({ pdf: calls.handler });
    stubUrls();
    await renderLive();
    await preview();
    showPdf();
    await settle();
    expect(pdfRequests(fetchMock)).toHaveLength(1);

    setValue(screen.getByLabelText("Paper"), "A3");
    await wait(QUIET_MS);
    setValue(screen.getByLabelText("Paper"), "A5");
    await wait(QUIET_MS);
    expect(pdfRequests(fetchMock)).toHaveLength(1);

    await calls.answer(0, pdfResponse());
    expect(pdfRequests(fetchMock)).toHaveLength(2);
    expect(pdfRequests(fetchMock).at(-1)?.get("paper")).toBe("A5");
  });

  it("asks again only when something changed while the pattern was shown", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubUrls();
    await renderLive();
    await preview();
    showPdf();
    await settle();

    fireEvent.click(screen.getByRole("radio", { name: "Pattern" }));
    showPdf();
    await settle();
    expect(pdfRequests(fetchMock)).toHaveLength(1);
    expect(frameUrl()).toBe("blob:pdf-1");

    fireEvent.click(screen.getByRole("radio", { name: "Pattern" }));
    setValue(screen.getByLabelText("Paper"), "A3");
    await wait(2000);
    expect(pdfRequests(fetchMock)).toHaveLength(1);

    showPdf();
    await settle();
    expect(pdfRequests(fetchMock)).toHaveLength(2);
  });

  it("shows the API's message on a failure and keeps the PDF shown", async () => {
    let answers = 0;
    stubApi({
      pdf: () => {
        answers += 1;
        return Promise.resolve(answers === 1 ? pdfResponse() : refused("pages_across", "too many"));
      },
    });
    stubUrls();
    await renderLive();
    await preview();
    showPdf();
    await settle();

    setValue(screen.getByLabelText("Paper"), "A3");
    await wait(QUIET_MS);
    await settle();

    expect(screen.getByText("pages_across: too many")).toBeInTheDocument();
    expect(frameUrl()).toBe("blob:pdf-1");
  });

  it("downloads the PDF shown without asking again, and asks once the choices changed", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    const click = stubUrls();
    await renderLive();
    await preview();
    showPdf();
    await settle();

    fireEvent.click(downloadButton());
    await settle();
    expect(pdfRequests(fetchMock)).toHaveLength(1);
    expect(click).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("radio", { name: "Pattern" }));
    setValue(screen.getByLabelText("Paper"), "A3");
    fireEvent.click(downloadButton());
    await settle();
    expect(pdfRequests(fetchMock)).toHaveLength(2);
  });

  it("waits to be asked for a pattern over the bound", async () => {
    const big = {
      ...PATTERN,
      width: 501,
      height: 500,
      grid: Array.from({ length: 500 }, () => Array.from({ length: 501 }, () => 0)),
    };
    const fetchMock = stubApi({
      patterns: () => Promise.resolve(json(200, big)),
      pdf: () => Promise.resolve(pdfResponse()),
    });
    stubUrls();
    await renderLive();
    await preview();
    showPdf();
    await settle();
    expect(pdfRequests(fetchMock)).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Generate preview" }));
    await settle();
    expect(pdfRequests(fetchMock)).toHaveLength(1);
    expect(frameUrl()).toBe("blob:pdf-1");

    setValue(screen.getByLabelText("Paper"), "A3");
    await wait(2000);
    expect(pdfRequests(fetchMock)).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Generate preview" })).toBeInTheDocument();
    expect(frameUrl()).toBe("blob:pdf-1");
  });

  it("revokes the PDF shown when another image is chosen and on unmount", async () => {
    stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubUrls();
    const view = await renderLive();
    await preview();
    showPdf();
    await settle();

    chooseFile("other.png");
    expect(revoked).toContain("blob:pdf-1");

    await wait(QUIET_MS);
    await settle();
    showPdf();
    await settle();
    const shown = frameUrl();
    view.unmount();
    expect(revoked).toContain(shown);
  });
});
