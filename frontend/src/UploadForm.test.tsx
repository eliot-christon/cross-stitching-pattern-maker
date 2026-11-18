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
  changed_cells: [],
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
  changed_cells: [],
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

/** A `/chart/layout` answer: the cells split in one page, every pages split allowed up
 * to 3 across and 3 down at 3.4 mm, the rest refused. */
const LAYOUT = {
  layout: {
    cell_mm: 3,
    columns: [{ start: 0, end: 4, repeated: 0 }],
    rows: [{ start: 0, end: 3, repeated: 0 }],
    sections: [["A1"]],
  },
  message: null,
  pages: Array.from({ length: 20 }, (_, d) =>
    Array.from({ length: 20 }, (_, a) => ({
      cell_mm: a < 3 && d < 3 ? 3.4 : null,
      columns: 40,
      rows: 30,
    })),
  ),
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
  handlers: { patterns?: Handler; pdf?: Handler; inspect?: Handler; layout?: Handler } = {},
): ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>> {
  const patterns = handlers.patterns ?? (() => Promise.resolve(json(200, PATTERN)));
  const layout = handlers.layout ?? (() => Promise.resolve(json(200, LAYOUT)));
  const pdf = handlers.pdf ?? (() => Promise.reject(new Error("no PDF expected")));
  const inspect =
    handlers.inspect ??
    (() =>
      Promise.resolve(
        json(200, { kind: "picture", description: "Picture", grid: null, warnings: [], refusal: null }),
      ));
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === "/api/limits") {
      return Promise.resolve(json(200, LIMITS));
    }
    if (url === "/api/images/inspect") {
      return inspect(init);
    }
    if (url === "/api/chart/layout") {
      return layout(init);
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
  await screen.findByLabelText("Image", { selector: "input" });
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

/**
 * `element`, with the settings tab that holds it selected first when its panel is hidden:
 * the way a person reaches a control in another tab.
 */
function reveal<T extends HTMLElement>(element: T): T {
  const panel = element.closest('[role="tabpanel"]');
  if (panel !== null && panel.hasAttribute("hidden")) {
    const tab = document.getElementById(panel.getAttribute("aria-labelledby") ?? "");
    if (tab !== null) {
      fireEvent.click(tab);
    }
  }
  return element;
}

/** Select the settings tab named `name`. */
function showTab(name: "Image" | "Pattern" | "Chart") {
  fireEvent.click(screen.getByRole("tab", { name }));
}

function numberField(name: string): HTMLElement {
  return reveal(screen.getByRole("spinbutton", { name, hidden: true }));
}

function slider(name: string): HTMLElement {
  return reveal(screen.getByRole("slider", { name, hidden: true }));
}

function fabricCount(): HTMLElement {
  return reveal(screen.getByLabelText("Fabric count"));
}

function imageInput(): HTMLElement {
  return screen.getByLabelText("Image", { selector: "input" });
}

function chooseFile(name = "photo.png", bytes = "png bytes"): File {
  const file = new File([bytes], name, { type: "image/png" });
  fireEvent.change(imageInput(), { target: { files: [file] } });
  return file;
}

/** The radio named `name` in the group named `group`. */
function option(group: string, name: string): HTMLElement {
  return reveal(
    within(screen.getByRole("group", { name: group, hidden: true })).getByRole("radio", { name, hidden: true }),
  );
}

/** Choose the option named `name` in the group named `group`. */
function choose(group: string, name: string) {
  fireEvent.click(option(group, name));
}

function setValue(field: HTMLElement, value: string) {
  fireEvent.change(field, { target: { value } });
}

/** Whether the key on screen lists the thread `code`: which response the preview shows. */
function keyShows(code: string): boolean {
  return screen.queryByRole("cell", { name: code }) !== null;
}

function downloadButton(): HTMLElement {
  return reveal(screen.getByRole("button", { name: /pdf/i, hidden: true }));
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
    expect(screen.queryByLabelText("Image", { selector: "input" })).not.toBeInTheDocument();
  });

  it("says so, with no form, when the limits cannot be fetched", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    render(<UploadForm />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot reach the server/i);
    expect(screen.queryByLabelText("Image", { selector: "input" })).not.toBeInTheDocument();
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
    expect(numberField(CONFETTI)).toHaveAttribute("max", "10");
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
    setValue(numberField(CONFETTI), "3");
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
      control: "confetti stepper field",
      field: () => numberField(CONFETTI),
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

    choose("Chart", "Black and white");
    choose("Paper", "A3");
    choose("Orientation", "Landscape");

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

    setValue(numberField(CONFETTI), "3");
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
    expect(screen.queryByRole("button", { name: /pdf/i, hidden: true })).not.toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: /pdf/i, hidden: true })).not.toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: /pdf/i, hidden: true })).not.toBeInTheDocument();
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

function pdfResponse(): Response {
  return new Response("%PDF-1.4 chart", {
    status: 200,
    headers: { "Content-Type": "application/pdf" },
  });
}

/** Stub object URLs and link clicks, so a PDF can be shown or saved in jsdom. */
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

describe("UploadForm PDF download", () => {
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

    expect(screen.queryByRole("button", { name: /pdf/i, hidden: true })).not.toBeInTheDocument();
  });

  it("offers the download with colour, A4 and portrait chosen after a conversion", async () => {
    stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    await renderLive();

    await convert();

    expect(downloadButton()).toHaveTextContent("Download PDF");
    expect(downloadButton()).toBeEnabled();
    expect(option("Chart", "Colour")).toBeChecked();
    expect(option("Paper", "A4")).toBeChecked();
    expect(option("Orientation", "Portrait")).toBeChecked();
    const papers = within(screen.getByRole("group", { name: "Paper" }))
      .getAllByRole("radio")
      .map((radio) => radio.closest("label")?.textContent);
    expect(papers).toEqual(["A2", "A3", "A4", "A5"]);
  });

  it("asks for the PDF of the preview shown, with the choices made, and saves it", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    const { createObjectURL, click } = stubSave();
    await renderLive();

    setValue(numberField(CONFETTI), "3");
    await convert("40");
    choose("Chart", "Black and white");
    choose("Paper", "A3");
    choose("Orientation", "Landscape");
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

describe("the changes list", () => {
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

  /** The replacements in the `changes` field of each conversion posted, as FROM:TO. */
  function sentReplacements(fetchMock: ReturnType<typeof stubApi>): string[][] {
    return posted(fetchMock, "/api/patterns").map((body) => replacementsIn(body));
  }

  function replacementsIn(body: FormData | undefined): string[] {
    const field = body?.get("changes");
    if (typeof field !== "string") {
      return [];
    }
    const entries = JSON.parse(field) as { op: string; from: string; to: string | null }[];
    return entries.map((entry) => `${entry.from}:${entry.to ?? "fabric"}`);
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
    const list = screen.queryByRole("list", { name: "Edits and replacements" });
    return list === null ? [] : within(list).getAllByRole("listitem");
  }

  /** Click the Remove button of the entry at `index` (0-based) in the Changes panel. */
  function removeEntry(index: number) {
    fireEvent.click(within(replacementItems()[index] as HTMLElement).getByRole("button", { name: /Remove/ }));
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

    removeEntry(0);
    await replace("310", "Winter White");
    await wait(10 * QUIET_MS);

    expect(sentReplacements(fetchMock)).toEqual([[], ["310:3865"]]);
  });

  it("sends a removal with a null TO and lists it as fabric, with its remove", async () => {
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();

    fireEvent.click(screen.getByRole("cell", { name: "310" }));
    await settle();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /Remove/ }));
    await wait(QUIET_MS);
    await settle();

    expect(sentReplacements(fetchMock)).toEqual([[], ["310:fabric"]]);
    expect(replacementItems()).toHaveLength(1);
    expect(replacementItems()[0]).toHaveTextContent(/310.*Black.*Fabric/);

    removeEntry(0);
    await wait(QUIET_MS);
    await settle();
    expect(sentReplacements(fetchMock)).toEqual([[], ["310:fabric"], []]);
  });

  it("sends no changes field once the only pair is removed, and empties the list", async () => {
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    await wait(QUIET_MS);
    await settle();

    removeEntry(0);
    await wait(QUIET_MS);
    await settle();

    expect(sentReplacements(fetchMock)).toEqual([[], ["310:3865"], []]);
    expect(posted(fetchMock, "/api/patterns").at(-1)?.has("changes")).toBe(false);
    expect(replacementItems()).toHaveLength(0);
  });

  it("sends one request with no changes field after a reset of two pairs", async () => {
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    await replace("321", "Black Brown");
    await wait(QUIET_MS);
    await settle();
    expect(sentReplacements(fetchMock).at(-1)).toEqual(["310:3865", "321:3371"]);

    fireEvent.click(screen.getByRole("button", { name: "Reset all" }));
    await wait(QUIET_MS);
    await settle();

    expect(sentReplacements(fetchMock)).toEqual([[], ["310:3865", "321:3371"], []]);
  });

  it("marks the pair the response counts 0, and keeps the mark on it after a remove", async () => {
    stubWithThreads({
      patterns: () => Promise.resolve(json(200, { ...PATTERN, changed_cells: [1, 0] })),
    });
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    await replace("321", "Black Brown");
    await wait(QUIET_MS);
    await settle();

    const [first, second] = replacementItems();
    expect(first).toHaveTextContent("1 cells");
    expect(first).not.toHaveTextContent(/not in the pattern/);
    expect(second).toHaveTextContent(/321.*not in the pattern/);

    removeEntry(0);

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
    expect(replacementsIn(last)).toEqual(["310:3865"]);
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
    expect(replacementsIn(pdfs[0])).toEqual(["310:3865"]);
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
    expect(replacementsIn(last)).toEqual(["310:3865"]);
    expect(replacementItems()).toHaveLength(1);
  });

  it("undoes a pick with Ctrl+Z and redoes it with Ctrl+Shift+Z", async () => {
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    await wait(QUIET_MS);
    await settle();

    fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
    await wait(QUIET_MS);
    await settle();
    expect(replacementItems()).toHaveLength(0);
    expect(posted(fetchMock, "/api/patterns").at(-1)?.has("changes")).toBe(false);

    fireEvent.keyDown(document.body, { key: "Z", ctrlKey: true, shiftKey: true });
    await wait(QUIET_MS);
    await settle();
    expect(replacementItems()).toHaveLength(1);
    expect(sentReplacements(fetchMock)).toEqual([[], ["310:3865"], [], ["310:3865"]]);
  });

  it("leaves the list alone on Ctrl+Z typed in the width field", async () => {
    stubWithThreads();
    await renderLive();
    await preview();
    await replace("310", "Winter White");

    fireEvent.keyDown(numberField(WIDTH), { key: "z", ctrlKey: true });

    expect(replacementItems()).toHaveLength(1);
  });

  it("resets the merge distance from its chip to the reported default, and converts", async () => {
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();
    setValue(numberField(MERGE), "2.5");
    await wait(QUIET_MS);
    await settle();

    fireEvent.click(screen.getByRole("button", { name: "Reset merge distance" }));
    expect(numberField(MERGE)).toHaveValue(LIMITS.settings.merge_distance.default);
    await wait(QUIET_MS);
    await settle();

    expect(sent(fetchMock, "merge_distance")).toEqual(["0", "2.5", "0"]);
  });

  it("refuses a pick past the most entries the API takes, with a message", async () => {
    stubWithThreads();
    const most = { ...LIMITS, changes: { ...LIMITS.changes, max_entries: 1 } };
    const inner = vi.mocked(fetch);
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) =>
        url === "/api/limits" ? Promise.resolve(json(200, most)) : inner(url, init),
      ),
    );
    await renderLive();
    await preview();
    await replace("310", "Winter White");

    await replace("321", "Black Brown");

    expect(replacementItems()).toHaveLength(1);
    expect(screen.getByRole("region", { name: "Changes" })).toHaveTextContent(/At most 1 changes/);
  });

  // Hand edits: the viewer measures 160 x 160 here, so PATTERN (2 x 1) shows at 80 px per
  // cell from y = 40; cell (column, 0) is under (column * 80 + 40, 80).
  function stubViewerSize() {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(160);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(160);
  }

  /** Pencil from cell (0, 0) to cell (1, 0) of PATTERN. */
  function strokeAcross() {
    fireEvent.click(screen.getByRole("radio", { name: "Pencil" }));
    const box = screen.getByRole("group", { name: /^Pattern viewer/ });
    fireEvent.pointerDown(box, { clientX: 40, clientY: 80, pointerId: 1 });
    fireEvent.pointerMove(box, { clientX: 120, clientY: 80, pointerId: 1 });
    fireEvent.pointerUp(box, { clientX: 120, clientY: 80, pointerId: 1 });
  }

  const STROKE = { op: "stroke", thread: "321", brush: 1, grid: [2, 1], points: [[0, 0], [1, 0]] };

  function sentChanges(body: FormData | undefined): unknown[] {
    const field = body?.get("changes");
    return typeof field === "string" ? (JSON.parse(field) as unknown[]) : [];
  }

  function changeItems(): HTMLElement[] {
    return replacementItems();
  }

  it("lists a stroke as a Pencil entry, sends it last after the quiet delay, and shows its count", async () => {
    stubViewerSize();
    let calls = 0;
    const fetchMock = stubWithThreads({
      patterns: () => {
        calls += 1;
        return Promise.resolve(json(200, calls === 1 ? PATTERN : { ...PATTERN, changed_cells: [1] }));
      },
    });
    await renderLive();
    await preview();

    strokeAcross();
    expect(changeItems()).toHaveLength(1);
    expect(changeItems()[0]).toHaveTextContent(/Pencil.*321.*1 × 1/);
    await wait(QUIET_MS);
    await settle();

    expect(sentChanges(posted(fetchMock, "/api/patterns").at(-1)).at(-1)).toEqual(STROKE);
    expect(changeItems()[0]).toHaveTextContent("1 cells");
  });

  it("drops the hand edits when a response has another size, keeping replacements, with no request", async () => {
    stubViewerSize();
    const TALL: Pattern = { ...PATTERN, height: 2, grid: [[0, 1], [1, 0]] };
    let calls = 0;
    const fetchMock = stubWithThreads({
      patterns: () => {
        calls += 1;
        return Promise.resolve(json(200, calls < 3 ? PATTERN : TALL));
      },
    });
    await renderLive();
    await preview();
    await replace("310", "Winter White");
    strokeAcross();
    await wait(QUIET_MS);
    await settle();
    expect(changeItems()).toHaveLength(2);

    setValue(numberField(WIDTH), "55");
    await wait(QUIET_MS);
    await settle();
    const sentBefore = posted(fetchMock, "/api/patterns").length;
    await wait(10 * QUIET_MS);
    await settle();

    expect(changeItems()).toHaveLength(1);
    expect(changeItems()[0]).toHaveTextContent(/Replace.*310/);
    expect(screen.getByRole("region", { name: "Changes" })).toHaveTextContent(
      "1 hand edit dropped: the pattern is now 2 × 2.",
    );
    expect(posted(fetchMock, "/api/patterns")).toHaveLength(sentBefore);

    fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
    expect(changeItems()).toHaveLength(2);
  });

  it("drops the hand edits when another image is chosen, saying so", async () => {
    stubViewerSize();
    const fetchMock = stubWithThreads();
    await renderLive();
    await preview();
    strokeAcross();
    await wait(QUIET_MS);
    await settle();

    chooseFile("other.png");
    await wait(QUIET_MS);
    await settle();

    expect(changeItems()).toHaveLength(0);
    expect(screen.getByRole("region", { name: "Changes" })).toHaveTextContent(
      "1 hand edit dropped: another image was chosen.",
    );
    expect(sentImages(fetchMock).at(-1)).toBe("other.png");
    expect(posted(fetchMock, "/api/patterns").at(-1)?.has("changes")).toBe(false);
  });

  it("asks for the PDF with the stroke once the preview has it", async () => {
    stubViewerSize();
    const fetchMock = stubWithThreads({ pdf: () => Promise.resolve(pdfResponse()) });
    stubSave();
    await renderLive();
    await preview();
    strokeAcross();
    await wait(QUIET_MS);
    await settle();

    fireEvent.click(downloadButton());
    await settle();

    const pdfs = posted(fetchMock, "/api/patterns/pdf");
    expect(pdfs).toHaveLength(1);
    expect(sentChanges(pdfs[0])).toEqual([STROKE]);
  });
});

describe("PDF chart layout", () => {

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

  /** The sheet standing for `across` x `down` pages in the pages picker. */
  function pageCell(across: number, down: number): HTMLElement {
    return screen.getByRole("button", { name: `${String(across)} across, ${String(down)} down` });
  }

  it("shows the pages picker only for a split by pages, at the reported 2 x 2", async () => {
    stubApi();
    await renderLive();
    await preview();

    choose("Split", "By pages");
    await wait(QUIET_MS);
    await settle();
    expect(pageCell(2, 2)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/2 × 2 = 4 pages, 3.4 mm cells, up to 40 × 30 cells each/)).toBeInTheDocument();

    choose("Split", "By cell size (3 mm)");
    expect(screen.queryByRole("group", { name: "Pages across and down" })).not.toBeInTheDocument();
  });

  it("disables the splits the API refuses and shows the sheets turned with the paper", async () => {
    stubApi();
    await renderLive();
    await preview();

    choose("Split", "By pages");
    await wait(QUIET_MS);
    await settle();
    expect(pageCell(3, 3)).toBeEnabled();
    expect(pageCell(4, 1)).toBeDisabled();
    const grid = screen.getByRole("group", { name: "Pages across and down" });
    expect(grid).toHaveClass("page-grid-portrait");

    choose("Orientation", "Landscape");
    expect(screen.getByRole("group", { name: "Pages across and down" })).toHaveClass("page-grid-landscape");
  });

  it("asks the API how the chart is cut, with the size and choices, after the quiet delay", async () => {
    const fetchMock = stubApi();
    await renderLive();
    await preview();
    await wait(QUIET_MS);
    await settle();

    choose("Paper", "A3");
    await wait(QUIET_MS);
    await settle();

    const bodies = posted(fetchMock, "/api/chart/layout");
    expect(bodies.length).toBeGreaterThanOrEqual(2);
    const last = bodies.at(-1);
    expect([last?.get("width"), last?.get("height"), last?.get("paper")]).toEqual(["2", "1", "A3"]);
    expect(screen.getByRole("img", { name: /Chart sections: 1 page/ })).toBeInTheDocument();
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

    choose("Split", "By pages");
    await wait(QUIET_MS);
    await settle();
    fireEvent.click(pageCell(3, 2));
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

    choose("Paper", "A3");
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

    choose("Paper", "A3");
    await wait(QUIET_MS);
    choose("Paper", "A5");
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
    choose("Paper", "A3");
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

    choose("Paper", "A3");
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
    choose("Paper", "A3");
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

    choose("Paper", "A3");
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

describe("source kind", () => {
  function inspection(fields: Record<string, unknown> = {}) {
    return { kind: "picture", description: "Picture", grid: null, warnings: [], refusal: null, ...fields };
  }

  const ART = inspection({
    kind: "pixel_art",
    description: "Pixel art, 64 x 64 stitches, 6 colours",
    grid: { width: 64, height: 64, colours: 6 },
  });

  function photoSwitch(): HTMLElement | null {
    return screen.queryByRole("checkbox", { name: "Treat as a photo" });
  }

  function widthNumber(): HTMLElement {
    return within(reveal(screen.getByRole("group", { name: "Width (stitches)", hidden: true }))).getByRole("spinbutton");
  }

  async function choose(found: Record<string, unknown>, name = "sprite.png") {
    const fetchMock = stubApi({ inspect: () => Promise.resolve(json(200, found)) });
    await renderLive();
    chooseFile(name);
    await settle();
    await wait(QUIET_MS);
    await settle();
    return fetchMock;
  }

  it("reads a grid kind once, at the grid's size and colours, with the width fixed", async () => {
    const fetchMock = await choose(ART);

    expect(screen.getByText("Detected: Pixel art, 64 x 64 stitches, 6 colours")).toBeInTheDocument();
    expect(sent(fetchMock, "read_as")).toEqual(["pixel_art"]);
    expect(sent(fetchMock, "width")).toEqual(["64"]);
    expect(sent(fetchMock, "max_colours")).toEqual(["6"]);
    expect(photoSwitch()).not.toBeChecked();
    expect(widthNumber()).toBeDisabled();
  });

  it("converts as a picture with the width editable once treated as a photo", async () => {
    const fetchMock = await choose(ART);

    fireEvent.click(photoSwitch() as HTMLElement);
    await wait(QUIET_MS);
    await settle();

    expect(sent(fetchMock, "read_as")).toEqual(["pixel_art", "picture"]);
    expect(widthNumber()).toBeEnabled();
  });

  it("shows a refusal and converts nothing until treated as a photo", async () => {
    const refusal = "fabric found but no stitch grid";
    const fetchMock = await choose(inspection({ refusal }), "photo.jpg");

    expect(screen.getByRole("alert")).toHaveTextContent(refusal);
    expect(sent(fetchMock, "read_as")).toEqual([]);

    fireEvent.click(photoSwitch() as HTMLElement);
    await wait(QUIET_MS);
    await settle();

    expect(sent(fetchMock, "read_as")).toEqual(["picture"]);
  });

  it("shows a refusal with no switch and converts nothing for what is no image", async () => {
    const refusal = "PDF charts cannot be read";
    const fetchMock = await choose(inspection({ kind: null, description: "PDF document", refusal }), "a.pdf");

    expect(screen.getByRole("alert")).toHaveTextContent(refusal);
    expect(photoSwitch()).not.toBeInTheDocument();
    expect(sent(fetchMock, "read_as")).toEqual([]);
  });

  it("shows every warning", async () => {
    await choose({ ...ART, warnings: ["first warning", "second warning"] });

    expect(screen.getByText("first warning")).toBeInTheDocument();
    expect(screen.getByText("second warning")).toBeInTheDocument();
  });

  it("keeps the settings and shows no switch for a picture", async () => {
    const fetchMock = stubApi();
    await renderLive();

    chooseFile();
    await settle();
    await wait(QUIET_MS);
    await settle();

    expect(sent(fetchMock, "width")).toEqual(["100"]);
    expect(sent(fetchMock, "max_colours")).toEqual(["7"]);
    expect(sent(fetchMock, "read_as")).toEqual(["picture"]);
    expect(screen.getByText("Detected: Picture")).toBeInTheDocument();
    expect(photoSwitch()).not.toBeInTheDocument();
    expect(widthNumber()).toBeEnabled();
  });

  it("converts as a picture when the inspection fails", async () => {
    const fetchMock = stubApi({ inspect: () => Promise.reject(new Error("offline")) });
    await renderLive();

    chooseFile();
    await settle();
    await wait(QUIET_MS);
    await settle();

    expect(sent(fetchMock, "read_as")).toEqual(["picture"]);
    expect(photoSwitch()).not.toBeInTheDocument();
  });

  it("caps the colours found at the colour limit", async () => {
    const fetchMock = await choose({ ...ART, grid: { width: 40, height: 40, colours: 250 } });

    expect(sent(fetchMock, "max_colours")).toEqual(["100"]);
  });
});

describe("crop", () => {
  /** Drag a box on the crop view: the image 1000 x 500 shown at 400 x 200. */
  async function drawCrop(from: [number, number], to: [number, number]) {
    // The image is read in the page (FileReader): let that finish, on the faked clock.
    await settle();
    const image = screen.getByAltText("The chosen image, to crop");
    Object.defineProperty(image, "naturalWidth", { value: 1000, configurable: true });
    Object.defineProperty(image, "naturalHeight", { value: 500, configurable: true });
    image.getBoundingClientRect = () => new DOMRect(0, 0, 400, 200);
    fireEvent.load(image);
    const area = image.parentElement as HTMLElement;
    fireEvent.pointerDown(area, { clientX: from[0], clientY: from[1], pointerId: 1 });
    fireEvent.pointerMove(area, { clientX: to[0], clientY: to[1], pointerId: 1 });
    fireEvent.pointerUp(area, { clientX: to[0], clientY: to[1], pointerId: 1 });
  }

  function inspected(fetchMock: ReturnType<typeof stubApi>): unknown[] {
    return posted(fetchMock, "/api/images/inspect").map((body) => body.get("crop"));
  }

  async function quiet() {
    await wait(QUIET_MS);
    await settle();
  }

  it("inspects again with the box, then converts with it; reset drops it", async () => {
    const fetchMock = stubApi();
    await renderLive();
    chooseFile();
    await settle();
    await quiet();
    expect(inspected(fetchMock)).toEqual([null]);
    expect(sent(fetchMock, "crop")).toEqual([null]);

    await drawCrop([40, 20], [200, 120]);
    await settle();
    expect(inspected(fetchMock)).toEqual([null]);
    await quiet();
    expect(inspected(fetchMock)).toEqual([null, "100,50,500,300"]);
    expect(sent(fetchMock, "crop")).toEqual([null]);
    await quiet();
    expect(sent(fetchMock, "crop")).toEqual([null, "100,50,500,300"]);

    fireEvent.click(screen.getByRole("button", { name: "Reset crop" }));
    await quiet();
    await quiet();
    expect(inspected(fetchMock)).toEqual([null, "100,50,500,300", null]);
    expect(sent(fetchMock, "crop")).toEqual([null, "100,50,500,300", null]);
  });

  it("keeps a drawn box after leaving the Image tab and coming back", async () => {
    stubApi();
    await renderLive();
    chooseFile();
    await settle();
    await quiet();
    await drawCrop([40, 20], [200, 120]);

    showTab("Chart");
    showTab("Image");

    expect(screen.getByRole("button", { name: "Reset crop" })).toBeVisible();
    expect(screen.getByText("Crop 400 × 250 px")).toBeVisible();
  });

  it("drops the box when another image is chosen", async () => {
    const fetchMock = stubApi();
    await renderLive();
    chooseFile("first.png");
    await settle();
    await quiet();
    await drawCrop([40, 20], [200, 120]);
    await quiet();
    await quiet();

    chooseFile("second.png");
    await settle();
    await quiet();

    expect(inspected(fetchMock).at(-1)).toBeNull();
    expect(sent(fetchMock, "crop").at(-1)).toBeNull();
    expect(sentImages(fetchMock).at(-1)).toBe("second.png");
  });

  it("sends the box of the preview shown with the PDF", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubSave();
    await renderLive();
    chooseFile();
    await settle();
    await quiet();
    await drawCrop([40, 20], [200, 120]);
    await quiet();
    await quiet();

    fireEvent.click(downloadButton());
    await settle();

    expect(posted(fetchMock, "/api/patterns/pdf").map((body) => body.get("crop"))).toEqual([
      "100,50,500,300",
    ]);
  });
});

describe("settings tabs and adjustments", () => {
  async function quiet() {
    await wait(QUIET_MS);
    await settle();
  }

  function tab(name: string): HTMLElement {
    return screen.getByRole("tab", { name });
  }

  function panel(name: string): HTMLElement {
    return screen.getByRole("tabpanel", { name });
  }

  /** The value of `field` in each inspection posted, in order. */
  function inspectedWith(fetchMock: ReturnType<typeof stubApi>, field: string): unknown[] {
    return posted(fetchMock, "/api/images/inspect").map((body) => body.get(field));
  }

  it("opens on the Image tab with the drop zone; width in Pattern, Download PDF in Chart", async () => {
    stubApi();
    await renderLive();

    expect(tab("Image")).toHaveAttribute("aria-selected", "true");
    expect(within(panel("Image")).getByLabelText("Image", { selector: "input" })).toBeInTheDocument();
    showTab("Pattern");
    expect(within(panel("Pattern")).getByRole("slider", { name: WIDTH })).toBeVisible();
    showTab("Chart");
    expect(panel("Chart")).toHaveTextContent("The chart choices come with the pattern.");

    chooseFile();
    await quiet();
    expect(within(panel("Chart")).getByRole("button", { name: /download pdf/i })).toBeVisible();
  });

  it("keeps a typed width across tab switches", async () => {
    stubApi();
    await renderLive();
    showTab("Pattern");
    setValue(numberField(WIDTH), "120");

    showTab("Image");
    showTab("Pattern");

    expect(numberField(WIDTH)).toHaveValue(120);
  });

  it("stays on the Chart tab through a new response and another image", async () => {
    stubApi();
    await renderLive();
    chooseFile();
    await quiet();
    showTab("Chart");

    chooseFile("other.png");
    await quiet();
    await quiet();

    expect(keyShows(A_CODE)).toBe(true);
    expect(tab("Chart")).toHaveAttribute("aria-selected", "true");
  });

  it("shows the conversion status and the API's error while the Chart tab is shown", async () => {
    stubApi({ patterns: () => Promise.resolve(json(400, { detail: "the image is too dark" })) });
    await renderLive();
    showTab("Chart");

    chooseFile();
    expect(screen.getByRole("status")).toHaveTextContent(BUSY);
    await quiet();

    expect(screen.getByRole("alert")).toHaveTextContent("the image is too dark");
    expect(tab("Chart")).toHaveAttribute("aria-selected", "true");
  });

  it("takes the six adjustment sliders' range, step and starting value from the limits", async () => {
    stubApi();
    await renderLive();

    const sliders = {
      Brightness: LIMITS.settings.brightness,
      Contrast: LIMITS.settings.contrast,
      Saturation: LIMITS.settings.saturation,
      Hue: LIMITS.settings.hue,
      Gamma: LIMITS.settings.gamma,
      Sharpness: LIMITS.settings.sharpness,
    };
    for (const [name, limits] of Object.entries(sliders)) {
      const range = within(panel("Image")).getByRole("slider", { name });
      expect(range).toHaveAttribute("min", String(limits.min));
      expect(range).toHaveAttribute("max", String(limits.max));
      expect(range).toHaveAttribute("step", String(limits.step));
      expect(range).toHaveValue(String(limits.default));
    }
  });

  it("re-inspects with a brightness change after the quiet delay, then converts with it", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubSave();
    await renderLive();
    chooseFile();
    await quiet();
    expect(inspectedWith(fetchMock, "brightness")).toEqual(["0"]);

    setValue(numberField("Brightness"), "20");
    await wait(QUIET_MS - 1);
    expect(inspectedWith(fetchMock, "brightness")).toEqual(["0"]);
    await wait(1);
    await settle();
    expect(inspectedWith(fetchMock, "brightness")).toEqual(["0", "20"]);
    expect(sent(fetchMock, "brightness")).toEqual(["0"]);
    await quiet();
    expect(sent(fetchMock, "brightness")).toEqual(["0", "20"]);

    fireEvent.click(downloadButton());
    await settle();
    expect(posted(fetchMock, "/api/patterns/pdf").map((body) => body.get("brightness"))).toEqual(["20"]);
  });

  it("chips a brightness off its default; the chip's reset puts it back and re-inspects", async () => {
    const fetchMock = stubApi();
    await renderLive();
    chooseFile();
    await quiet();
    setValue(numberField("Brightness"), "-30");
    await quiet();
    await quiet();

    expect(within(screen.getByRole("region", { name: "Changes" })).getByText("Brightness -30")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reset brightness" }));
    expect(numberField("Brightness")).toHaveValue(LIMITS.settings.brightness.default);
    await quiet();

    expect(inspectedWith(fetchMock, "brightness")).toEqual(["0", "-30", "0"]);
  });

  it("keeps the adjustments for another image and inspects it with them", async () => {
    const fetchMock = stubApi();
    await renderLive();
    chooseFile();
    await quiet();
    setValue(numberField("Saturation"), "-100");
    await quiet();
    await quiet();

    chooseFile("other.png");
    await quiet();

    expect(numberField("Saturation")).toHaveValue(-100);
    expect(inspectedWith(fetchMock, "saturation").at(-1)).toBe("-100");
    expect(sent(fetchMock, "saturation").at(-1)).toBe("-100");
    expect(sentImages(fetchMock).at(-1)).toBe("other.png");
  });
});

describe("background as fabric", () => {
  function backgroundSwitch(): HTMLElement {
    return screen.getByRole("checkbox", { name: "Background as fabric" });
  }

  it("is off at first, and turning it on converts once more with it on", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubSave();
    await renderLive();
    chooseFile();
    await settle();
    await wait(QUIET_MS);
    await settle();
    expect(backgroundSwitch()).not.toBeChecked();
    expect(sent(fetchMock, "background_as_fabric")).toEqual(["false"]);

    fireEvent.click(backgroundSwitch());
    await wait(QUIET_MS);
    await settle();
    expect(sent(fetchMock, "background_as_fabric")).toEqual(["false", "true"]);

    fireEvent.click(downloadButton());
    await settle();
    expect(posted(fetchMock, "/api/patterns/pdf").map((body) => body.get("background_as_fabric"))).toEqual([
      "true",
    ]);
  });

  it("stays on when another image is chosen", async () => {
    const fetchMock = stubApi();
    await renderLive();
    chooseFile("first.png");
    await settle();
    await wait(QUIET_MS);
    await settle();
    fireEvent.click(backgroundSwitch());
    await wait(QUIET_MS);
    await settle();

    chooseFile("second.png");
    await settle();
    await wait(QUIET_MS);
    await settle();

    expect(sentImages(fetchMock).at(-1)).toBe("second.png");
    expect(sent(fetchMock, "background_as_fabric").at(-1)).toBe("true");
  });
});

describe("fabric colour", () => {
  it("sends the fabric chosen with the next PDF request, white until then", async () => {
    const fetchMock = stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    stubSave();
    await renderLive();
    chooseFile();
    await settle();
    await wait(QUIET_MS);
    await settle();

    const fabric = reveal(screen.getByRole("group", { name: "Fabric colour", hidden: true }));
    expect(within(fabric).getByRole("radio", { name: "White" })).toBeChecked();
    fireEvent.click(within(fabric).getByRole("radio", { name: "Black" }));
    fireEvent.click(downloadButton());
    await settle();

    expect(posted(fetchMock, "/api/patterns/pdf").map((body) => body.get("fabric_colour"))).toEqual([
      "#1e1e1e",
    ]);
  });
});

describe("fabric count chips", () => {
  it("converts with the count of the chip chosen", async () => {
    const fetchMock = stubApi();
    await renderLive();
    chooseFile();
    await settle();
    await wait(QUIET_MS);
    await settle();

    choose("Fabric count", "18");
    await wait(QUIET_MS);
    await settle();

    expect(sent(fetchMock, "fabric_count")).toEqual(["14", "18"]);
    expect(fabricCount()).toHaveValue(18);
  });
});
