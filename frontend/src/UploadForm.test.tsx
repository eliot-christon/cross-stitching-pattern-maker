import { act, fireEvent, render, screen } from "@testing-library/react";
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
    { code: "321", name: "Red", rgb: [199, 43, 59], stitches: 1, skeins: 1, symbol: "A" },
    { code: "310", name: "Black", rgb: [0, 0, 0], stitches: 1, skeins: 1, symbol: "B" },
  ],
  total_stitches: 2,
  finished_size: { width_in: 0.14, height_in: 0.07, width_cm: 0.36, height_cm: 0.18 },
  isolated_stitches: { before: 2, after: 0 },
};

/** Limits unlike the API's real ones, so a number hard-coded in the page fails a test. */
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

const WIDTH = "Width (stitches)";
const COLOURS = "Max colours";
const MERGE = "Merge similar threads (colour distance)";
const MIN_STITCHES = "Minimum stitches per thread";
const CONFETTI = "Largest confetti cluster (stitches)";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
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

/** Render the form and wait until the limits are in and it is shown. */
async function renderForm() {
  render(<UploadForm />);
  await screen.findByLabelText("Image");
}

function numberField(name: string): HTMLElement {
  return screen.getByRole("spinbutton", { name });
}

function slider(name: string): HTMLElement {
  return screen.getByRole("slider", { name });
}

function chooseFile(): File {
  const file = new File(["png bytes"], "photo.png", { type: "image/png" });
  fireEvent.change(screen.getByLabelText("Image"), { target: { files: [file] } });
  return file;
}

function submitButton(): HTMLElement {
  return screen.getByRole("button", { name: /convert/i });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("UploadForm limits", () => {
  it("shows a status and no form while the limits load", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    render(<UploadForm />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading the settings/i);
    expect(screen.queryByRole("button", { name: /convert/i })).not.toBeInTheDocument();
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

    expect(screen.getByLabelText("Fabric count")).toHaveValue(14);
    expect(screen.queryByRole("slider", { name: "Fabric count" })).not.toBeInTheDocument();
  });

  it("moves the number field with the slider and posts the slider's value", async () => {
    const fetchMock = stubApi();
    await renderForm();

    chooseFile();
    fireEvent.change(slider(CONFETTI), { target: { value: "3" } });
    expect(numberField(CONFETTI)).toHaveValue(3);
    fireEvent.click(submitButton());

    await screen.findByRole("table", { name: "Thread key" });
    expect(posted(fetchMock, "/api/patterns")[0]?.get("confetti_size")).toBe("3");
  });

  it("moves the slider with the number field", async () => {
    stubApi();
    await renderForm();

    fireEvent.change(numberField(WIDTH), { target: { value: "250" } });

    expect(slider(WIDTH)).toHaveValue("250");
  });

  it("refuses an image over the reported upload limit without converting", async () => {
    const fetchMock = stubApi();
    await renderForm();

    const big = new File(["x".repeat(1001)], "big.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Image"), { target: { files: [big] } });
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("larger than 1000 bytes");
    expect(posted(fetchMock, "/api/patterns")).toHaveLength(0);
  });
});

describe("UploadForm", () => {
  it("starts with the default settings and submit disabled until a file is chosen", async () => {
    stubApi();
    await renderForm();

    expect(numberField(WIDTH)).toHaveValue(100);
    expect(numberField(COLOURS)).toHaveValue(7);
    expect(screen.getByLabelText("Fabric count")).toHaveValue(14);
    expect(numberField(MERGE)).toHaveValue(0);
    expect(numberField(MIN_STITCHES)).toHaveValue(0);
    expect(numberField(CONFETTI)).toHaveValue(0);
    expect(submitButton()).toBeDisabled();

    chooseFile();

    expect(submitButton()).toBeEnabled();
  });

  it("posts the chosen file with the values entered", async () => {
    const fetchMock = stubApi();
    await renderForm();

    const file = chooseFile();
    fireEvent.change(numberField(WIDTH), { target: { value: "40" } });
    fireEvent.change(numberField(COLOURS), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Fabric count"), { target: { value: "16" } });
    fireEvent.change(numberField(MERGE), { target: { value: "2.5" } });
    fireEvent.change(numberField(MIN_STITCHES), { target: { value: "10" } });
    fireEvent.change(numberField(CONFETTI), { target: { value: "3" } });
    fireEvent.click(submitButton());

    expect(await screen.findByRole("table", { name: "Thread key" })).toBeInTheDocument();
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
    await renderForm();

    chooseFile();
    fireEvent.click(submitButton());

    await screen.findByRole("table", { name: "Thread key" });
    const body = posted(fetchMock, "/api/patterns")[0] as FormData;
    expect(body.get("width")).toBe("100");
    expect(body.get("max_colours")).toBe("7");
    expect(body.get("fabric_count")).toBe("14");
    expect(body.get("merge_distance")).toBe("0");
    expect(body.get("min_stitches")).toBe("0");
    expect(body.get("confetti_size")).toBe("0");
  });

  it("shows the field of a refused cleanup setting from the API's 422", async () => {
    const detail = [
      {
        loc: ["body", "confetti_size"],
        msg: "Input should be less than or equal to 10",
        type: "less_than_equal",
      },
    ];
    stubApi({ patterns: () => Promise.resolve(json(422, { detail })) });
    await renderForm();

    chooseFile();
    fireEvent.change(numberField(CONFETTI), { target: { value: "11" } });
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "confetti_size: Input should be less than or equal to 10",
    );
  });

  it("shows a busy state while the request is in flight, then the preview", async () => {
    let resolve: (response: Response) => void = () => undefined;
    stubApi({
      patterns: () =>
        new Promise<Response>((r) => {
          resolve = r;
        }),
    });
    await renderForm();

    chooseFile();
    fireEvent.click(submitButton());

    expect(screen.getByRole("status")).toHaveTextContent(/converting/i);
    expect(submitButton()).toBeDisabled();

    await act(async () => {
      resolve(json(200, PATTERN));
    });

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(submitButton()).toBeEnabled();
    expect(screen.getByText("321")).toBeInTheDocument();
    expect(screen.getByText("310")).toBeInTheDocument();
  });

  it("shows the API's message on an error", async () => {
    stubApi({
      patterns: () =>
        Promise.resolve(json(400, { detail: "the upload is not a decodable image" })),
    });
    await renderForm();

    chooseFile();
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "the upload is not a decodable image",
    );
  });

  it("clears the error when the next submit succeeds", async () => {
    const patterns = vi
      .fn<Handler>()
      .mockResolvedValueOnce(json(400, { detail: "the upload is not a decodable image" }))
      .mockResolvedValueOnce(json(200, PATTERN));
    stubApi({ patterns });
    await renderForm();

    chooseFile();
    fireEvent.click(submitButton());
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    fireEvent.click(submitButton());

    expect(await screen.findByRole("table", { name: "Thread key" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("clears the previous preview when the next submit fails", async () => {
    const patterns = vi
      .fn<Handler>()
      .mockResolvedValueOnce(json(200, PATTERN))
      .mockResolvedValueOnce(json(400, { detail: "the upload is not a decodable image" }));
    stubApi({ patterns });
    await renderForm();

    chooseFile();
    fireEvent.click(submitButton());
    expect(await screen.findByRole("table", { name: "Thread key" })).toBeInTheDocument();

    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Thread key" })).not.toBeInTheDocument();
  });

  it("posts a width of 0 as typed: the form does no range check", async () => {
    const fetchMock = stubApi({
      patterns: () =>
        Promise.resolve(
          json(422, {
            detail: [{ loc: ["body", "width"], msg: "Input should be greater than or equal to 1" }],
          }),
        ),
    });
    await renderForm();

    chooseFile();
    fireEvent.change(numberField(WIDTH), { target: { value: "0" } });
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "width: Input should be greater than or equal to 1",
    );
    expect(posted(fetchMock, "/api/patterns")[0]?.get("width")).toBe("0");
  });

  it("shows a message, not a crash, when the server cannot be reached", async () => {
    stubApi({ patterns: () => Promise.reject(new TypeError("Failed to fetch")) });
    await renderForm();

    chooseFile();
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot reach the server/i);
    expect(submitButton()).toBeEnabled();
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

  async function convert(width = "40") {
    chooseFile();
    fireEvent.change(numberField(WIDTH), { target: { value: width } });
    fireEvent.click(submitButton());
    await screen.findByRole("table", { name: "Thread key" });
  }

  function downloadButton(): HTMLElement {
    return screen.getByRole("button", { name: /pdf/i });
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("offers no download before a conversion", async () => {
    stubApi();
    await renderForm();

    expect(screen.queryByRole("button", { name: /pdf/i })).not.toBeInTheDocument();
  });

  it("offers the download with colour, A4 and portrait chosen after a conversion", async () => {
    stubApi({ pdf: () => Promise.resolve(pdfResponse()) });
    await renderForm();

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
    await renderForm();

    fireEvent.change(numberField(CONFETTI), { target: { value: "3" } });
    await convert("40");
    fireEvent.change(numberField(WIDTH), { target: { value: "80" } });
    fireEvent.change(numberField(CONFETTI), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Chart"), { target: { value: "bw" } });
    fireEvent.change(screen.getByLabelText("Paper"), { target: { value: "A3" } });
    fireEvent.change(screen.getByLabelText("Orientation"), { target: { value: "landscape" } });
    fireEvent.click(downloadButton());

    await vi.waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    const pdfs = posted(fetchMock, "/api/patterns/pdf");
    expect(pdfs).toHaveLength(1);
    const body = pdfs[0] as FormData;
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

  it("disables the button and says so while the PDF is being made", async () => {
    let resolve: (response: Response) => void = () => undefined;
    stubApi({ pdf: () => new Promise<Response>((done) => (resolve = done)) });
    stubSave();
    await renderForm();
    await convert();

    fireEvent.click(downloadButton());

    expect(await screen.findByRole("button", { name: "Preparing PDF..." })).toBeDisabled();

    await act(async () => resolve(pdfResponse()));

    expect(downloadButton()).toHaveTextContent("Download PDF");
    expect(downloadButton()).toBeEnabled();
  });

  it("shows the API's message on a failed download and keeps the preview", async () => {
    stubApi({
      pdf: () =>
        Promise.resolve(json(422, { detail: [{ loc: ["body", "paper"], msg: "bad paper" }] })),
    });
    await renderForm();
    await convert();

    fireEvent.click(downloadButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("paper: bad paper");
    expect(screen.getByRole("table", { name: "Thread key" })).toBeInTheDocument();
  });
});
