import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

const MERGE = "Merge similar threads (colour distance)";
const MIN_STITCHES = "Minimum stitches per thread";
const CONFETTI = "Largest confetti cluster (stitches)";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
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

describe("UploadForm", () => {
  it("starts with the default settings and submit disabled until a file is chosen", () => {
    render(<UploadForm />);

    expect(screen.getByLabelText("Width (stitches)")).toHaveValue(100);
    expect(screen.getByLabelText("Max colours")).toHaveValue(20);
    expect(screen.getByLabelText("Fabric count")).toHaveValue(14);
    expect(screen.getByLabelText(MERGE)).toHaveValue(0);
    expect(screen.getByLabelText(MIN_STITCHES)).toHaveValue(0);
    expect(screen.getByLabelText(CONFETTI)).toHaveValue(0);
    expect(submitButton()).toBeDisabled();

    chooseFile();

    expect(submitButton()).toBeEnabled();
  });

  it("posts the chosen file with the values entered", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(json(200, PATTERN)));
    vi.stubGlobal("fetch", fetchMock);
    render(<UploadForm />);

    const file = chooseFile();
    fireEvent.change(screen.getByLabelText("Width (stitches)"), { target: { value: "40" } });
    fireEvent.change(screen.getByLabelText("Max colours"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Fabric count"), { target: { value: "16" } });
    fireEvent.change(screen.getByLabelText(MERGE), { target: { value: "2.5" } });
    fireEvent.change(screen.getByLabelText(MIN_STITCHES), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(CONFETTI), { target: { value: "3" } });
    fireEvent.click(submitButton());

    expect(await screen.findByRole("table", { name: "Thread key" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/patterns");
    const body = init.body as FormData;
    expect((body.get("image") as File).name).toBe(file.name);
    expect(body.get("width")).toBe("40");
    expect(body.get("max_colours")).toBe("4");
    expect(body.get("fabric_count")).toBe("16");
    expect(body.get("merge_distance")).toBe("2.5");
    expect(body.get("min_stitches")).toBe("10");
    expect(body.get("confetti_size")).toBe("3");
  });

  it("posts the cleanup settings as 0 when left alone", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(json(200, PATTERN)));
    vi.stubGlobal("fetch", fetchMock);
    render(<UploadForm />);

    chooseFile();
    fireEvent.click(submitButton());

    await screen.findByRole("table", { name: "Thread key" });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const body = init.body as FormData;
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
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json(422, { detail }))));
    render(<UploadForm />);

    chooseFile();
    fireEvent.change(screen.getByLabelText(CONFETTI), { target: { value: "11" } });
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "confetti_size: Input should be less than or equal to 10",
    );
  });

  it("shows a busy state while the request is in flight, then the preview", async () => {
    let resolve: (response: Response) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((r) => {
            resolve = r;
          }),
      ),
    );
    render(<UploadForm />);

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
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(json(400, { detail: "the upload is not a decodable image" }))),
    );
    render(<UploadForm />);

    chooseFile();
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "the upload is not a decodable image",
    );
  });

  it("clears the error when the next submit succeeds", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(400, { detail: "the upload is not a decodable image" }))
      .mockResolvedValueOnce(json(200, PATTERN));
    vi.stubGlobal("fetch", fetchMock);
    render(<UploadForm />);

    chooseFile();
    fireEvent.click(submitButton());
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    fireEvent.click(submitButton());

    expect(await screen.findByRole("table", { name: "Thread key" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("clears the previous preview when the next submit fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(200, PATTERN))
      .mockResolvedValueOnce(json(400, { detail: "the upload is not a decodable image" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<UploadForm />);

    chooseFile();
    fireEvent.click(submitButton());
    expect(await screen.findByRole("table", { name: "Thread key" })).toBeInTheDocument();

    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Thread key" })).not.toBeInTheDocument();
  });

  it("posts a width of 0 as typed: the form does no range check", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        json(422, {
          detail: [{ loc: ["body", "width"], msg: "Input should be greater than or equal to 1" }],
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<UploadForm />);

    chooseFile();
    fireEvent.change(screen.getByLabelText("Width (stitches)"), { target: { value: "0" } });
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "width: Input should be greater than or equal to 1",
    );
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.body as FormData).get("width")).toBe("0");
  });

  it("shows a message, not a crash, when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    render(<UploadForm />);

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

  /** fetch answering the conversion with PATTERN and the PDF request with `pdf`. */
  function stubBoth(pdf: () => Promise<Response>) {
    const fetchMock = vi.fn((url: string) =>
      url === "/api/patterns" ? Promise.resolve(json(200, PATTERN)) : pdf(),
    );
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
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
    fireEvent.change(screen.getByLabelText("Width (stitches)"), { target: { value: width } });
    fireEvent.click(submitButton());
    await screen.findByRole("table", { name: "Thread key" });
  }

  function downloadButton(): HTMLElement {
    return screen.getByRole("button", { name: /pdf/i });
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("offers no download before a conversion", () => {
    render(<UploadForm />);

    expect(screen.queryByRole("button", { name: /pdf/i })).not.toBeInTheDocument();
  });

  it("offers the download with colour, A4 and portrait chosen after a conversion", async () => {
    stubBoth(() => Promise.resolve(pdfResponse()));
    render(<UploadForm />);

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
    const fetchMock = stubBoth(() => Promise.resolve(pdfResponse()));
    const { createObjectURL, click } = stubSave();
    render(<UploadForm />);

    fireEvent.change(screen.getByLabelText(CONFETTI), { target: { value: "3" } });
    await convert("40");
    fireEvent.change(screen.getByLabelText("Width (stitches)"), { target: { value: "80" } });
    fireEvent.change(screen.getByLabelText(CONFETTI), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Chart"), { target: { value: "bw" } });
    fireEvent.change(screen.getByLabelText("Paper"), { target: { value: "A3" } });
    fireEvent.change(screen.getByLabelText("Orientation"), { target: { value: "landscape" } });
    fireEvent.click(downloadButton());

    await vi.waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [url, init] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect(url).toBe("/api/patterns/pdf");
    const body = init.body as FormData;
    expect(body.get("width")).toBe("40");
    expect(body.get("max_colours")).toBe("20");
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
    stubBoth(() => new Promise<Response>((done) => (resolve = done)));
    stubSave();
    render(<UploadForm />);
    await convert();

    fireEvent.click(downloadButton());

    expect(await screen.findByRole("button", { name: "Preparing PDF..." })).toBeDisabled();

    await act(async () => resolve(pdfResponse()));

    expect(downloadButton()).toHaveTextContent("Download PDF");
    expect(downloadButton()).toBeEnabled();
  });

  it("shows the API's message on a failed download and keeps the preview", async () => {
    stubBoth(() =>
      Promise.resolve(json(422, { detail: [{ loc: ["body", "paper"], msg: "bad paper" }] })),
    );
    render(<UploadForm />);
    await convert();

    fireEvent.click(downloadButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("paper: bad paper");
    expect(screen.getByRole("table", { name: "Thread key" })).toBeInTheDocument();
  });
});
